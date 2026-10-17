"""Measured recovery accuracy for the web interface.

Accuracy only means something against ground truth, so every result names the truth it used:

  organizer          the organizer's published answer key for the kit file (independent truth)
  organizer-damaged  the same answer key, applied to a copy the UI damaged on purpose
  undamaged          the tool's own output for the undamaged kit file, verified records only, applied to a damaged
                     copy (a regression comparison, not independent proof: the key itself is the tool's output)
  none               no answer key exists; nothing is claimed

The counting rules are `deadbits.validation.reference.record_accuracy` / `differences`, the same code behind
`salvage --verify`, so the figures match the command line. Nothing here changes how files are recovered.
"""
import hashlib
import json
import os
from pathlib import Path

from .engine import salvage_bytes
from .validation import reference

# Graded record fields per format (samples/official/OUTPUT-CONTRACT.md); tools/ is not packaged, so they live here.
KEYS = {"LIBRA-98": ["id"], "LABLOG": ["sample"], "VAULT": ["id"], "WKS": ["cell"], "WPD": ["index"],
        "BRAVO": ["index"], "CVT": ["slot"], "EBCDIC-DUMP": ["student_id"], "WAD": ["name"], "PAK": ["name"]}
FIELDS = {
    "LIBRA-98": "id title author year price_cents copies isbn checked_out deleted reference_only due_date",
    "LABLOG": "sample time_ms values",
    "VAULT": "id name type size sha256 compressed text width height",
    "WKS": "cell row col type value alignment number_format iso_date cached_value formula_raw_hex",
    "WPD": "index type text", "BRAVO": "index text", "CVT": "slot text",
    "EBCDIC-DUMP": "student_id name dob gpa credits status balance",
    "WAD": "name offset size sha256", "PAK": "name offset size sha256"}
# What can actually catch a wrong value in each format (FORMAT-SPEC.md): drives the honesty note on wrong-but-verified.
INTEGRITY = {"LIBRA-98": "checksum", "LABLOG": "checksum", "VAULT": "size"}

BASIS_LABELS = {
    "organizer": "The organizer's answer key (independent)",
    "organizer-damaged": "The organizer's answer key, for a copy damaged on purpose",
    "undamaged": "The undamaged copy of this file (regression comparison, not independent)",
    "none": "No answer key available",
}
MAX_WRONG = 30
MAX_FIELDS = 12
MAX_KEYS = 50

_REASONS = (
    ("duplicate record identities", "The recovered file lists the same record identity more than once, so records cannot be matched one to one."),
    ("matching fields", "Some recovered records lack the field that identifies them, so they cannot be matched to the answer key."),
    ("overlap", "The answer key lists the same identity as required and optional."),
)


def friendly_reason(error):
    text = str(error)
    for needle, message in _REASONS:
        if needle in text:
            return message
    return "Records could not be matched to the answer key (%s)." % text


def is_verified(record):
    return record.get("verified") is not False and not record.get("issues")


def graded(record, fmt):
    return {k: record[k] for k in FIELDS.get(fmt, "").split() if k in record}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _strict_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Truth:
    """Where answers come from: the kit's samples/ and expected_outputs/ folders (both read-only)."""

    def __init__(self, samples_dir, expected_dir=None):
        self.samples_dir = Path(samples_dir)
        self.expected_dir = Path(expected_dir) if expected_dir else self.samples_dir.parent / "expected_outputs"
        self._hashes = None
        self._baselines = {}

    def _index(self):
        if self._hashes is None:
            hashes, sizes = {}, set()
            try:
                entries = sorted(os.scandir(self.samples_dir), key=lambda e: e.name)
            except OSError:
                entries = []
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    try:
                        data = Path(entry.path).read_bytes()
                    except OSError:
                        continue
                    hashes.setdefault(sha256(data), entry.name)
                    sizes.add(len(data))
            self._hashes = (hashes, sizes)
        return self._hashes

    def sample_for(self, name, size, read):
        """Kit sample whose bytes equal this file, or None. `read` is only called when the size could match."""
        hashes, sizes = self._index()
        if size not in sizes:
            return None
        return hashes.get(sha256(read()))

    def sample_bytes(self, sample):
        try:
            return (self.samples_dir / sample).read_bytes()
        except OSError:
            return None

    def organizer(self, sample):
        path = self.expected_dir / (sample + ".json")
        doc = _strict_json(path) if path.is_file() else None
        if not isinstance(doc, dict) or not isinstance(doc.get("records"), list) or "format" not in doc:
            return None
        return doc

    def undamaged(self, sample):
        """Answer key made of the tool's own verified output for the undamaged kit file."""
        if sample not in self._baselines:
            data = self.sample_bytes(sample)
            baseline = None
            if data is not None:
                doc = salvage_bytes(data, sample).to_dict()
                keys = KEYS.get(doc["format"])
                verified = [graded(r, doc["format"]) for r in doc["records"] if is_verified(r)]
                if keys and verified:
                    baseline = {"format": doc["format"], "status": doc["status"], "match_on": keys,
                                "records": verified,
                                "optional_partial_records": [graded(r, doc["format"]) for r in doc["records"]
                                                             if not is_verified(r)]}
            self._baselines[sample] = baseline
        return self._baselines[sample]

    def resolve(self, name, size, read, origin):
        """-> dict(basis, sample, mutate, expected, reason). Never guesses from the file name."""
        mutate = (origin or {}).get("mutate", "")
        sample = (origin or {}).get("sample") or self.sample_for(name, size, read)
        out = {"basis": "none", "sample": sample, "mutate": mutate, "expected": None, "reason": None}
        if sample is None:
            out["reason"] = "This is not one of the kit's sample files, so there is no answer key to compare with."
            return out
        key = self.organizer(sample)
        if key is not None:
            out.update(basis="organizer-damaged" if mutate else "organizer", expected=key)
            return out
        if not mutate:
            out["reason"] = ("The kit publishes no answer key for %s, and comparing the tool with its own output "
                             "would prove nothing. Damage a copy on purpose to measure how much survives." % sample)
            return out
        baseline = self.undamaged(sample)
        if baseline is None:
            out["reason"] = "The undamaged file holds no verified records to compare with."
            return out
        out.update(basis="undamaged", expected=baseline)
        return out


def score(actual, expected):
    """Counts and detail for one recovered file against an answer key (answer-key formats only)."""
    try:
        acc = reference.record_accuracy(actual, expected)
    except ValueError as exc:
        return {"available": False, "reason": friendly_reason(exc)}
    match_on = expected.get("match_on", ["id"])
    got = {reference.key(r, match_on): r for r in actual["records"]}
    want = {reference.key(r, match_on): r for r in expected["records"]}
    optional = {reference.key(r, match_on) for r in expected.get("optional_partial_records", [])}
    fields_expected = fields_correct = false_verified = 0
    wrong, missing = [], []
    for identity, record in want.items():
        fields_expected += len(record)
        current = got.get(identity)
        if current is None:
            missing.append(list(identity))
            continue
        diffs = [{"field": f, "expected": v, "actual": current.get(f)} for f, v in record.items()
                 if actual["format"] != expected["format"] or current.get(f) != v]
        fields_correct += len(record) - len(diffs) if actual["format"] == expected["format"] else 0
        if diffs:
            verified = is_verified(current)
            false_verified += int(verified)
            wrong.append({"key": list(identity), "verified": verified, "fields": diffs[:MAX_FIELDS],
                          "moreFields": max(0, len(diffs) - MAX_FIELDS)})
    unexpected = [list(i) for i in got if i not in want and i not in optional]
    try:
        errors = reference.differences(actual, expected)
    except (KeyError, TypeError):      # an answer key without status/damage entries: no agreement to report
        errors = None
    agreement = None if errors is None else {
        "status": not any(e["field"] == "status" for e in errors),
        "damage": not any(e["kind"] in ("missing_damage", "unexpected_damage") for e in errors),
        "metadata": not any(str(e["field"]).startswith("metadata.") for e in errors)}
    return {"available": True, "counts": acc.to_dict(),
            "fields": {"expected": fields_expected, "correct": fields_correct},
            "wrong": wrong[:MAX_WRONG], "moreWrong": max(0, len(wrong) - MAX_WRONG),
            "missing": missing[:MAX_KEYS], "unexpected": unexpected[:MAX_KEYS],
            "falseVerified": false_verified, "agreement": agreement}


def file_result(actual, truth_info):
    base = {"basis": truth_info["basis"], "basisLabel": BASIS_LABELS[truth_info["basis"]],
            "sample": truth_info["sample"], "mutate": truth_info["mutate"],
            "format": actual.get("format"), "integrity": INTEGRITY.get(actual.get("format"), "none")}
    if truth_info["expected"] is None:
        return dict(base, available=False, reason=truth_info["reason"])
    scored = score(actual, truth_info["expected"])
    if truth_info["basis"] != "organizer":
        scored.pop("agreement", None)    # status/damage agreement is only meaningful for the undamaged kit file
    return dict(base, **scored)


def summarize(files):
    """Totals per basis, never blended: different truths are different claims."""
    groups = {}
    skipped = 0
    for result in files.values():
        if not result.get("available"):
            skipped += 1
            continue
        g = groups.setdefault(result["basis"], {"files": 0, "expected": 0, "recovered": 0, "correct": 0, "wrong": 0,
                                                "missing": 0, "unexpected": 0, "falseVerified": 0})
        g["files"] += 1
        counts = result["counts"]
        for k in ("expected", "recovered", "correct", "wrong", "missing", "unexpected"):
            g[k] += counts[k]
        g["falseVerified"] += result["falseVerified"]
    for g in groups.values():
        g["recovery"] = g["recovered"] / g["expected"] if g["expected"] else None
        g["accuracy"] = g["correct"] / g["expected"] if g["expected"] else None
        denominator = g["recovered"] + g["unexpected"]
        g["precision"] = g["correct"] / denominator if denominator else None
    return {"groups": groups, "withoutAnswerKey": skipped}


def report(session_staged, session_out, session_inp, origins, truth):
    """Accuracy of every recovered file in a session. Reads the JSON the run wrote; never recovers anything itself."""
    files = {}
    for row in session_staged:
        name = row["name"]
        try:
            actual = json.loads((session_out / (name + ".json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            files[name] = {"basis": "none", "basisLabel": BASIS_LABELS["none"], "available": False,
                           "reason": "No result file exists for this input yet. Press Recover first."}
            continue
        info = truth.resolve(name, row["size"], lambda n=name: (session_inp / n).read_bytes(), origins.get(name))
        files[name] = file_result(actual, info)
    return {"files": files, "summary": summarize(files)}
