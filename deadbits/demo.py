"""Guided, offline mentor walkthrough using real recovery and validation outputs.

Run with ``salvage --demo --kit-dir KIT --output-dir NEW_DIR`` or the
standalone module. Both entry points use this parser and orchestration.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sys

from . import diagnostics, presentation
from .cli import run as recover
from .engine import salvage_bytes
from .version import VERSION


_MODES = ("verify", "test", "benchmark")
_CASES = ("normal", "truncation", "checksum", "unknown")
MAX_DEMO_SOURCE_BYTES = 2 * 1024 * 1024


def _json(path, document):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def _unverified(record):
    return record.get("verified") is False or bool(record.get("issues"))


def _select_source(samples):
    """Choose a healthy v2 LIBRA file with confirmed record/trailer framing.

    Only framing offsets are used to make copies. All field recovery remains
    with the engine; no field or checksum interpretation is reimplemented here.
    """
    if not samples.is_dir():
        return None
    for path in sorted(samples.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if not 16 < path.stat().st_size <= MAX_DEMO_SOURCE_BYTES:
                continue
            with path.open("rb") as stream:
                data = stream.read(MAX_DEMO_SOURCE_BYTES + 1)
        except OSError:
            continue
        if len(data) > MAX_DEMO_SOURCE_BYTES or data[:5] != b"LB98\x02" or data[-6:-2] != b"END!":
            continue
        doc = salvage_bytes(data, path.name).to_dict()
        if doc["format"] != "LIBRA-98" or doc["status"] != "ok" or not doc["records"]:
            continue
        spans, pos = [], int.from_bytes(data[12:14], "little")
        while 16 <= pos < len(data) - 6:
            if data[pos] != 0xA5 or pos + 1 >= len(data) - 6:
                break
            end = pos + 2 + data[pos + 1]
            if not pos + 7 < end <= len(data) - 6:
                break
            spans.append((pos, end))
            pos = end
        if spans and pos == len(data) - 6:
            return path, data, spans
    return None


def _plans(selected):
    plans = {}
    if selected is not None:
        path, data, spans = selected
        cut, checksum_offset = spans[-1][0] + 7, spans[0][1] - 1
        damaged = bytearray(data)
        damaged[checksum_offset] ^= 1
        shared = dict(source=str(path), source_sha256=hashlib.sha256(data).hexdigest())
        plans.update(normal=dict(data=data, mutation=dict(kind="copy"), **shared),
                     truncation=dict(data=data[:cut], mutation=dict(kind="truncate", keep_bytes=cut), **shared),
                     checksum=dict(data=bytes(damaged), mutation=dict(kind="xor", offset=checksum_offset, xor=1), **shared))
    plans["unknown"] = dict(data=b"\x00\xff\x00\xff", source=None, source_sha256=None,
                            mutation=dict(kind="synthetic_unknown", hex="00ff00ff"))
    return plans


def _observed(name, doc):
    if name == "normal":
        return doc["status"] == "ok" and bool(doc["records"])
    if name == "unknown":
        return doc["format"] == "UNKNOWN" and doc["status"] == "unrecognized"
    kind = "truncated" if name == "truncation" else "checksum_mismatch"
    return (any(damage["kind"] == kind for damage in doc["damage"])
            and any(_unverified(record) for record in doc["records"]))


def run_demo(*, kit_dir, output_dir, source_dir=None, historical=None,
             skip_validation=(), guided=False, stream=None, input_stream=None):
    """Save and present a new walkthrough; return its manifest dictionary.

    Historical maps verify/test/benchmark to existing schema-1 evidence files.
    It replaces only the selected validation step, never the current recoveries.
    Tests and source scoring require an explicit trusted source_dir. There are
    no prompts unless guided is requested AND both streams are interactive.
    """
    stream = sys.stdout if stream is None else stream
    input_stream = sys.stdin if input_stream is None else input_stream
    kit, output = Path(kit_dir).resolve(), Path(output_dir).resolve()
    source = Path(source_dir).resolve() if source_dir is not None else None
    historical = {mode: Path(path).resolve() for mode, path in (historical or {}).items()}
    skipped = set(skip_validation)
    if (set(historical) | skipped) - set(_MODES) or set(historical) & skipped:
        raise ValueError("choose valid, distinct historical or skipped validation steps")
    for root in (kit, source, diagnostics.source_root()):
        if root is not None and (output == root or root in output.parents or output in root.parents):
            raise ValueError("demo output must be separate from the kit and source checkout")
    output.mkdir(parents=True, exist_ok=False)
    transcript = []

    def say(text):
        transcript.append(text)
        presentation.emit(text, stream)

    interactive = (guided and getattr(stream, "isatty", lambda: False)()
                   and getattr(input_stream, "isatty", lambda: False)())

    def pause():
        nonlocal interactive
        if interactive:
            say("Press Enter to continue.")
            if not input_stream.readline():
                interactive = False
                say("Input ended; continuing without prompts.")

    manifest = dict(schema_version=1, app_version=VERSION,
                    recorded_at=datetime.now(timezone.utc).isoformat(), provenance="live",
                    environment=dict(python_version=platform.python_version(), platform=platform.platform()),
                    kit_dir=str(kit), source_dir=str(source) if source else None,
                    recovery=[], validation=[])
    say(presentation.banner('GUIDED DEMO  /  LIVE'))
    say("Mentor demo: current recovery run (live)\nKit: " + presentation.clean(kit))
    say(presentation.panel('THE WALKTHROUGH',
        '1  Healthy input    -> readable records\n'
        '2  Truncated copy   -> missing bytes and partial fields\n'
        '3  Checksum damage  -> readable but unverified records\n'
        '4  Unknown input    -> no invented records\n'
        '5  Validation       -> answers, tests and measured benchmarks'))
    if guided and not interactive:
        say("Guided prompts skipped: redirected/noninteractive streams; continuing automatically.")
    say("Recovery counts, reference agreement, test outcomes and record accuracy are separate measurements.")
    selected = _select_source(kit / "samples")
    plans = _plans(selected)
    inputs, recovered = output / "inputs", output / "recovered"
    inputs.mkdir()
    for name, plan in plans.items():
        with (inputs / (name + ".dat")).open("xb") as binary:
            binary.write(plan["data"])
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        recover(inputs, recovered)
    if errors.getvalue():
        say("Recovery diagnostics:\n" + "\n".join(presentation.clean(line) for line in errors.getvalue().splitlines()))
    for number, name in enumerate(_CASES, 1):
        say('\n' + presentation.panel('%d. %s recovery (live)' % (number, name.capitalize()),
            'Observe the input change, recovered fields and damage evidence.'))
        if name not in plans:
            detail = ("Unavailable: the kit needs a healthy version-2 LIBRA-98 sample with records, "
                      "confirmed framing and size <= 2 MiB. No replacement fields were invented.")
            manifest["recovery"].append(dict(step=name, status="unavailable", provenance="live", detail=detail))
            say(detail)
            pause()
            continue
        plan, path = plans[name], recovered / (name + ".dat.json")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            status = "complete" if _observed(name, doc) else "failed"
            say(presentation.byte_change(name, plan['mutation'],
                len(selected[1]) if selected is not None else 0, len(plan['data'])))
            manifest["recovery"].append(dict(step=name, status=status, provenance="live",
                input=str(inputs / (name + ".dat")), output=str(path), source=plan["source"],
                source_sha256=plan["source_sha256"], input_sha256=hashlib.sha256(plan["data"]).hexdigest(),
                mutation=plan["mutation"], format=doc["format"], file_status=doc["status"],
                records=len(doc["records"]), unverified_records=sum(_unverified(r) for r in doc["records"])))
            say("%s / %s; %d recovered records" % (doc["format"], doc["status"], len(doc["records"])))
            uncertain_count = sum(_unverified(r) for r in doc['records'])
            say(presentation.panel('RECOVERY RESULT',
                '%d records recovered | %d explicitly unverified | %d damage entries\n%s' %
                (len(doc['records']), uncertain_count, len(doc['damage']),
                 presentation._STATUS.get(doc['status'], doc['status']))))
            preview = doc["records"][:2]
            uncertain = next((r for r in doc["records"] if _unverified(r)), None)
            if uncertain is not None and uncertain not in preview:
                preview.append(uncertain)
            for record in preview:
                say(presentation.record_card(record))
            if len(doc["records"]) > len(preview):
                say("Additional records are in the saved JSON.")
            for damage in doc["damage"][:5]:
                say(presentation.panel('Damage at byte %s: %s' % (damage['offset'], damage['kind']),
                    '%s\nLoss reported: %s' % (presentation.clean(damage['detail']), damage['lossy'])))
            if len(doc["damage"]) > 5:
                say("Additional damage entries are in the saved JSON.")
            if status == "failed":
                say("Demonstration failed: this output did not exhibit the requested case.")
            say("Input: " + presentation.clean(inputs / (name + ".dat")))
            say("Saved JSON: " + presentation.clean(path))
        except (OSError, ValueError, KeyError, TypeError) as error:
            detail = "%s: %s" % (type(error).__name__, error)
            manifest["recovery"].append(dict(step=name, status="failed", provenance="live", detail=detail))
            say("Recovery output unavailable: " + presentation.clean(detail))
        pause()
    say("\nCombined recovery report: " + presentation.clean(recovered / "report.json"))
    say("Verification flags and issues above are exactly those emitted by the engine; structural checks have limits.")
    say("\n5. Validation evidence")
    for mode in _MODES:
        if mode in skipped:
            manifest["validation"].append(dict(step=mode, status="skipped", provenance=None,
                                               detail="Explicitly skipped; no measurement was run."))
            say(mode + ": skipped (explicit request; no measurement was run).")
            continue
        path = historical.get(mode)
        provenance = "historical" if path is not None else "live"
        say("\n%s validation (%s)" % (mode.capitalize(), provenance))
        say('[RUNNING] Loading saved proof...' if path is not None else
            '[RUNNING] Measuring %s with local resources; results follow when complete.' % mode)
        try:
            if path is not None:
                evidence = diagnostics.load_evidence(path, mode)
                sections = ([evidence.reference] if mode == "verify" else [evidence.tests]
                            if mode == "test" else list(evidence.benchmarks))
                if not sections or any(item is None or item.context.provenance != "historical" for item in sections):
                    raise FileNotFoundError("Saved evidence has no requested section; no current measurement was run.")
                say("Saved proof loaded; no current validation was executed. Artifact contents were not reverified.")
            else:
                path = output / "validation" / mode / "validation.json"
                if mode in ("test", "benchmark") and source is None:
                    evidence = diagnostics.unavailable(mode, "Supply --source-dir with a trusted source kit for this live step.")
                else:
                    request = diagnostics.ValidationRequest(source_dir=source, samples_dir=kit / "samples",
                        expected_dir=kit / "expected_outputs", evidence_dir=path.parent)
                    evidence = diagnostics.run_validation(mode, request)
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _json(path, evidence.to_dict())
            manifest["validation"].append(dict(step=mode, status=evidence.status, provenance=provenance,
                                               evidence_path=str(path), evidence=evidence.to_dict()))
            say(presentation.validation(evidence, evidence_file=path, compact=True))
            say("Evidence file: " + presentation.clean(path))
        except Exception as error:
            status = "unavailable" if isinstance(error, OSError) else "failed"
            detail = "%s: %s" % (type(error).__name__, error)
            manifest["validation"].append(dict(step=mode, status=status, provenance=provenance, detail=detail,
                                               evidence_path=str(path) if path else None))
            say(mode + ": " + status + "; " + presentation.clean(detail))
        pause()
    states = [step["status"] for step in manifest["recovery"] + manifest["validation"]]
    manifest["status"] = "failed" if "failed" in states else "unavailable" if any(s != "complete" for s in states) else "complete"
    say('\n' + presentation.panel('Demo: ' + manifest['status'],
        presentation.table(('Demonstration', 'State', 'Source'),
            [(step['step'], step['status'], step.get('provenance') or 'not run')
             for step in manifest['recovery'] + manifest['validation']]) +
        '\nCompletion means requested steps ran successfully, not perfect recovery.'))
    say("Walkthrough manifest: " + presentation.clean(output / "demo.json"))
    say("Saved transcript: " + presentation.clean(output / "transcript.txt"))
    _json(output / "demo.json", manifest)
    with (output / "transcript.txt").open("x", encoding="utf-8", newline="\n") as saved:
        saved.write("\n".join(transcript) + "\n")
    return manifest


def main(argv=None, *, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__, allow_abbrev=False)
    parser.add_argument("--kit-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="fresh output directory outside kit/source")
    parser.add_argument("--source-dir", type=Path, help="trusted source kit for live tests and benchmark scoring")
    parser.add_argument("--guided", action="store_true", help="pause between steps only on interactive streams")
    parser.add_argument("--skip-validation", action="append", choices=_MODES, default=[])
    parser.add_argument("--historical-evidence", action="append", default=[], metavar="MODE=PATH",
                        help="show existing proof for verify, test or benchmark instead of running that step")
    args = parser.parse_args(argv)
    historical = {}
    for item in args.historical_evidence:
        mode, separator, path = item.partition("=")
        if not separator or mode not in _MODES or not path or mode in historical:
            parser.error("historical evidence requires a unique verify/test/benchmark=PATH")
        historical[mode] = path
    if set(historical) & set(args.skip_validation):
        parser.error("a validation step cannot be both historical and skipped")
    try:
        result = run_demo(kit_dir=args.kit_dir, output_dir=args.output_dir, source_dir=args.source_dir,
                          historical=historical, skip_validation=args.skip_validation, guided=args.guided)
    except (OSError, ValueError) as error:
        presentation.emit("Demo error: " + presentation.clean(error), sys.stderr)
        return 1
    return {"complete": 0, "failed": 1, "unavailable": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
