"""Offline recovery (always exit 0) and explicit diagnostic/validation modes."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .engine import salvage_file
from .model import Result, STATUSES
from .version import VERSION

TOOL_VERSION = VERSION


def _dump(obj) -> bytes:
    """UTF-8/LF JSON; escape undecodable filename bytes without losing them."""
    return (json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n").encode("utf-8", errors="backslashreplace")


def _write_json(path, obj):
    """Atomic replacement also avoids following an existing output symlink."""
    payload = _dump(obj)
    fd, temporary = tempfile.mkstemp(prefix=".salvage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run(in_dir: Path, out_dir: Path) -> dict:
    if in_dir.resolve() == out_dir.resolve():
        raise ValueError("input and output directories must differ to protect source files")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"tool_version": TOOL_VERSION, "files": [], "totals": {s: 0 for s in STATUSES}}
    try:
        with os.scandir(in_dir) as entries:
            files = sorted((in_dir / entry.name for entry in entries
                            if not entry.is_dir(follow_symlinks=False)), key=lambda p: p.name)
    except OSError as exc:
        print("salvage: cannot read input directory: %s" % type(exc).__name__, file=sys.stderr)
        files = []
    produced = {}
    for p in files:
        res = salvage_file(p)
        try:
            doc = res.to_dict()
            _dump(doc)
        except Exception as exc:
            res = Result(p.name, "UNKNOWN", "failed")
            res.add_damage("unparsed_bytes", 0, "invalid decoder output", True)
            res.notes.append("invalid decoder output: %s" % type(exc).__name__)
            doc = res.to_dict()
        try:
            target = out_dir / (p.name + ".json")
            report_path = out_dir / "report.json"
            try:
                previous = target.lstat()
                collision = produced.get((previous.st_dev, previous.st_ino))
            except FileNotFoundError:
                collision = None
            if p.name == "report":
                res.notes.append("per-file JSON name collides with combined report.json")
                doc = dict(doc, status="failed")
            elif collision is not None:
                res.notes.append("per-file JSON name collides with output for %r" % collision)
                doc = dict(doc, status="failed")
            else:
                _write_json(target, doc)
                # Case sensitivity is a volume property (including on macOS).
                # Compare actual file identity instead of guessing from the OS.
                if report_path.exists() and target.samefile(report_path):
                    res.notes.append("per-file JSON name collides with combined report.json")
                    doc = dict(doc, status="failed")
                written = target.lstat()
                produced[(written.st_dev, written.st_ino)] = p.name
        except OSError as exc:
            # A filesystem may reject the mandated name, e.g. a 255-byte input
            # basename plus '.json'. Preserve the failure and process siblings.
            res.notes.append("could not write per-file JSON: %s" % type(exc).__name__)
            doc = dict(doc, status="failed")
        row = {"file": p.name, "format": doc["format"], "status": doc["status"],
               "records": len(doc["records"]), "damage": len(doc["damage"])}
        if res.notes:
            for note in res.notes:
                print("salvage: %s: %s" % (ascii(p.name), note), file=sys.stderr)
        report["files"].append(row)
        report["totals"][doc["status"]] += 1
    _write_json(out_dir / "report.json", report)
    return report


def _parser():
    parser = argparse.ArgumentParser(
        prog="salvage", allow_abbrev=False,
        description="Offline legacy recovery and validation evidence. Recovery lists inputs nonrecursively "
                    "and writes <input name>.json plus report.json. Use distinct input/output folders; "
                    "inspect statuses, damage and stderr for losses.",
        epilog="Recovery always exits 0. Demo/validation: 0 complete, 1 failed, 2 usage, 3 unavailable.")
    parser.add_argument("input_dir", nargs="?", type=Path)
    parser.add_argument("output_dir", nargs="?", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--interactive', action='store_true', help='open the beginner welcome menu')
    modes.add_argument("--version", action="store_true", help="show the application version")
    modes.add_argument("--demo", action="store_true",
                       help="run the mentor walkthrough; use --demo --help for options")
    for mode, help_text in (("doctor", "inspect interpreter, adapters and local resources"),
                            ("verify", "compare supplied references and measure record accuracy"),
                            ("test", "execute an explicitly selected source test suite"),
                            ("benchmark", "measure recovery against labelled baselines")):
        modes.add_argument("--" + mode, action="store_true", help=help_text)
    parser.add_argument("--verbose", action="store_true", help="show per-file counts or evidence provenance")
    parser.add_argument("--source-dir", type=Path, help="trusted local source checkout / extracted source kit")
    parser.add_argument("--kit-dir", type=Path, help="local kit containing samples/ and expected_outputs/")
    parser.add_argument("--samples-dir", type=Path, help="override kit samples path")
    parser.add_argument("--expected-dir", type=Path, help="override organizer reference path")
    parser.add_argument("--corpus-dir", type=Path, help="persisted benchmark variant corpus")
    parser.add_argument("--evidence-dir", type=Path, help="new output directory outside protected inputs")
    parser.add_argument("--evidence-file", type=Path, help="display saved validation evidence as historical")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ['--interactive'] or (not argv and sys.stdin.isatty() and sys.stdout.isatty()):
        from .welcome import run_menu
        return run_menu()
    # Delegate the complete demo grammar rather than duplicating its options.
    # Tokens after -- are literal recovery paths, including a folder named --demo.
    option_end = argv.index("--") if "--" in argv else len(argv)
    if "--demo" in argv[:option_end]:
        from .demo import main as demo_main
        position = argv.index("--demo")
        try:
            return demo_main(argv[:position] + argv[position + 1:], prog="salvage --demo")
        except SystemExit as exc:
            return exc.code or 0
        except Exception as exc:
            from . import presentation
            presentation.emit("salvage: demo error: %s: %s" % (type(exc).__name__, exc), sys.stderr)
            return 1
    parser = _parser()
    # Recovery retains its historical zero exit even on usage/operational failure.
    validation_requested = any(arg.split("=", 1)[0] in {"--doctor", "--verify", "--test", "--benchmark", "--demo", '--interactive'}
                               for arg in argv[:argv.index("--") if "--" in argv else len(argv)])
    try:
        args = parser.parse_args(argv)
        if args.interactive:
            parser.error('--interactive accepts no other options; choose a task from its menu')
        mode = next((name for name in ("doctor", "verify", "test", "benchmark")
                     if getattr(args, name)), None)
        has_paths = any(getattr(args, name) is not None for name in
                        ("source_dir", "kit_dir", "samples_dir", "expected_dir", "corpus_dir",
                         "evidence_dir", "evidence_file"))
        if mode or args.version:
            if args.input_dir is not None or args.output_dir is not None:
                parser.error("diagnostic/version modes do not accept recovery folders")
            if args.version and (has_paths or args.verbose):
                parser.error("--version does not accept validation options")
        elif args.input_dir is None or args.output_dir is None or has_paths:
            parser.error("recovery requires input_dir output_dir; path options require a validation mode")
        if args.evidence_file is not None and (mode not in ("verify", "test", "benchmark") or
                any(getattr(args, name) is not None for name in
                    ("source_dir", "kit_dir", "samples_dir", "expected_dir", "corpus_dir", "evidence_dir"))):
            parser.error("--evidence-file requires one validation mode and cannot combine with live paths")
        if mode == "doctor" and args.evidence_dir is not None:
            parser.error("--doctor is read-only and does not accept --evidence-dir")
    except SystemExit as exc:
        return (exc.code or 0) if validation_requested else 0
    from . import presentation
    if args.version:
        presentation.emit("salvage " + TOOL_VERSION, sys.stdout)
        return 0
    if mode:
        from . import diagnostics
        try:
            request = diagnostics.request_from(args)
            if mode == "doctor":
                rows, code = diagnostics.doctor(request)
                presentation.emit(presentation.banner('SYSTEM CHECK') + '\n' +
                                  presentation.panel('Installation diagnostics (presence checks only)',
                                  presentation.table(("Check", "Available", "Detail"),
                                  [(name, 'READY' if available else 'MISSING', detail)
                                   for name, available, detail in rows])), sys.stdout)
                return code
            evidence_path = args.evidence_file.resolve() if args.evidence_file else None
            evidence = (diagnostics.load_evidence(evidence_path, mode) if evidence_path else
                        diagnostics.run_validation(mode, request))
            presentation_path = evidence_path
            if presentation_path is None and request.evidence_dir is not None:
                presentation_path = request.evidence_dir / "validation.json"
            presentation.emit(presentation.validation(evidence, args.verbose, presentation_path), sys.stdout)
            return diagnostics.exit_code(evidence)
        except Exception as exc:
            presentation.emit("salvage: validation error: %s: %s" % (type(exc).__name__, exc), sys.stderr)
            return 1
    try:
        report = run(args.input_dir, args.output_dir)
        presentation.emit(presentation.recovery(report, args.verbose), sys.stdout)
        presentation.emit(presentation.panel('SAVED RESULTS',
            'Per-file JSON: ' + presentation.clean(args.output_dir.resolve()) + '\n' +
            'Combined report: ' + presentation.clean(args.output_dir.resolve() / 'report.json')), sys.stdout)
    except Exception as exc:
        presentation.emit("salvage: error: %s" % exc, sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
