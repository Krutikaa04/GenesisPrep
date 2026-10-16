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
from deadbits.validation.reference import compare, key  # noqa: E402,F401


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
