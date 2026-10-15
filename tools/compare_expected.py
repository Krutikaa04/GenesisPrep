"""Compare our output to the organizers' expected_outputs using their matching semantics.

  python tools/compare_expected.py [samples_dir] [expected_dir]

Semantics (from expected_outputs/*.json): `match_on` = key(s) identifying a record; every field present
in an expected record must equal ours; `optional_partial_records` may appear without penalty;
`expected_damage[{any_of:[kinds], lossy}]` -> at least one of our damage entries has a kind in any_of;
an empty expected_damage means we should report none.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deadbits.engine import salvage_file  # noqa: E402


def key(rec, match_on):
    return tuple(rec.get(k) for k in match_on)


def compare(actual: dict, exp: dict) -> list:
    errs = []
    for k in ("format", "status"):
        if actual[k] != exp[k]:
            errs.append("%s: got %r expected %r" % (k, actual[k], exp[k]))
    for k, v in exp.get("metadata", {}).items():
        if actual["metadata"].get(k) != v:
            errs.append("metadata.%s: got %r expected %r" % (k, actual["metadata"].get(k), v))
    mo = exp.get("match_on", ["id"])
    got = {key(r, mo): r for r in actual["records"]}
    want = {key(r, mo): r for r in exp["records"]}
    optional = {key(r, mo) for r in exp.get("optional_partial_records", [])}
    for k, er in want.items():
        ar = got.get(k)
        if ar is None:
            errs.append("missing record %s" % (k,))
            continue
        for f, v in er.items():
            if ar.get(f) != v:
                errs.append("record %s.%s: got %r expected %r" % (k, f, ar.get(f), v))
    for k in got:
        if k not in want and k not in optional:
            errs.append("extra record %s" % (k,))
    exp_d = exp.get("expected_damage", [])
    if not exp_d and actual["damage"]:
        errs.append("unexpected damage: %s" % [d["kind"] for d in actual["damage"]])
    for ed in exp_d:
        if not any(d["kind"] in ed["any_of"] for d in actual["damage"]):
            errs.append("expected damage any_of %s, got %s" % (ed["any_of"], [d["kind"] for d in actual["damage"]]))
    return errs


def main():
    root = Path(__file__).resolve().parent.parent / "samples" / "official"
    samples = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "samples"
    expd = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "expected_outputs"
    bad = 0
    for ep in sorted(expd.glob("*.json")):
        exp = json.loads(ep.read_text(encoding="utf-8"))
        res = salvage_file(samples / exp["file"])
        errs = compare(res.to_dict(), exp)
        print("%-4s %s" % ("PASS" if not errs else "FAIL", exp["file"]))
        for e in errs[:12]:
            print("       -", e)
        bad += bool(errs)
    print("%d/%d reference outputs matched" % (len(list(expd.glob("*.json"))) - bad, len(list(expd.glob("*.json")))))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
