"""salvage <input_dir> <output_dir> -- always exits 0."""
import json
import os
import sys
import tempfile
from pathlib import Path

from .engine import salvage_file
from .model import Result, STATUSES

TOOL_VERSION = "0.2.0"


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
            if p.name == "report":
                res.notes.append("per-file JSON name collides with combined report.json")
                doc = dict(doc, status="failed")
            else:
                _write_json(out_dir / (p.name + ".json"), doc)
        except OSError as exc:
            # A filesystem may reject the mandated name, e.g. a 255-byte input
            # basename plus '.json'. Preserve the failure and process siblings.
            res.notes.append("could not write per-file JSON: %s" % type(exc).__name__)
            doc = dict(doc, status="failed")
        row = {"file": p.name, "format": doc["format"], "status": doc["status"],
               "records": len(doc["records"]), "damage": len(doc["damage"])}
        if res.notes:
            row["notes"] = res.notes
        report["files"].append(row)
        report["totals"][doc["status"]] += 1
    _write_json(out_dir / "report.json", report)
    return report


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: salvage <input_dir> <output_dir>", file=sys.stderr)
        return 0
    try:
        r = run(Path(argv[0]), Path(argv[1]))
        t = r["totals"]
        print("salvage: %d files  %s" % (len(r["files"]), "  ".join("%s=%d" % (k, v) for k, v in t.items())))
    except Exception as exc:
        print("salvage: error: %s" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
