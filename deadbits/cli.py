"""salvage <input_dir> <output_dir>  -- always exits 0."""
import json
import sys
from pathlib import Path

from .engine import salvage_file
from .model import STATUSES

TOOL_VERSION = "0.1.0"


def _dump(obj) -> bytes:
    """LF-only UTF-8 so output is byte-identical on Windows and Linux."""
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def run(in_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"tool_version": TOOL_VERSION, "files": [], "totals": {s: 0 for s in STATUSES}}
    # non-recursive; directories skipped; deterministic order
    try:
        files = sorted((p for p in in_dir.iterdir() if p.is_file()), key=lambda p: p.name)
    except OSError as exc:
        report["error"] = "cannot read input directory: %s" % exc
        files = []
    for p in files:
        res = salvage_file(p)
        try:
            doc = res.to_dict()
        except Exception as exc:  # noqa: BLE001 - never emit a non-contract document
            res.status, res.format = "failed", "UNKNOWN"
            res.notes.append("contract violation: %s" % exc)
            doc = res.to_dict()
        (out_dir / (p.name + ".json")).write_bytes(_dump(doc))
        row = {"file": p.name, "format": doc["format"], "status": doc["status"],
               "records": len(doc["records"]), "damage": len(doc["damage"])}
        if res.notes:
            row["notes"] = res.notes
        report["files"].append(row)
        report["totals"][doc["status"]] += 1
    (out_dir / "report.json").write_bytes(_dump(report))
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
    except Exception as exc:  # noqa: BLE001
        print("salvage: error: %s" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
