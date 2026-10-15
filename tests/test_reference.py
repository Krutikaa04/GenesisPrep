"""Golden tests: our output vs the organizers' reference outputs (their matching semantics)."""
import json
import unittest

from helpers import EXPECTED, SAMPLES, salvage_bytes  # noqa: F401  (helpers sets sys.path)
from compare_expected import compare  # noqa: E402


class ReferenceOutputs(unittest.TestCase):
    def test_all_reference_outputs_match(self):
        files = sorted(EXPECTED.glob("*.json"))
        self.assertEqual(len(files), 7)
        for ep in files:
            exp = json.loads(ep.read_text(encoding="utf-8"))
            src = SAMPLES / exp["file"]
            res = salvage_bytes(src.read_bytes(), src.name)
            errs = compare(res.to_dict(), exp)
            self.assertEqual(errs, [], "%s: %s" % (exp["file"], errs))

    def test_libra_exact_records(self):
        exp = json.loads((EXPECTED / "s01.dat.json").read_text(encoding="utf-8"))
        res = salvage_bytes((SAMPLES / "s01.dat").read_bytes(), "s01.dat").to_dict()
        self.assertEqual(res["records"], exp["records"])           # full equality, not just graded fields
        self.assertEqual(res["metadata"], exp["metadata"])
        self.assertEqual(res["damage"], [])

    def test_unlabeled_samples_have_sensible_status(self):
        want = {"s02.dat": "ok", "s03.dat": "ok", "s06.dat": "ok", "s07.dat": "partial", "s09.dat": "ok",
                "s10.dat": "ok", "s12.wks": "partial", "s13.wks": "partial", "s15.wpd": "partial",
                "s19.cvt": "ok", "s21.000": "ok", "s22.000": "partial", "s23.wad": "ok", "s24.pak": "ok",
                "s25_random.bin": "unrecognized", "s26_empty.dat": "unrecognized", "s27_notes.txt": "unrecognized",
                "s28_tiny.dat": "unrecognized", "s29_almost_libra.dat": "failed", "s30_png_like.dat": "unrecognized"}
        for name, status in want.items():
            res = salvage_bytes((SAMPLES / name).read_bytes(), name)
            self.assertEqual(res.status, status, name)

    def test_damaged_kinds_on_known_damaged_samples(self):
        def kinds(n):
            return {d["kind"] for d in salvage_bytes((SAMPLES / n).read_bytes(), n).damage}
        self.assertIn("truncated", kinds("s04.dat"))
        self.assertIn("crc_mismatch", kinds("s07.dat"))
        self.assertIn("unknown_record", kinds("s12.wks"))
        self.assertIn("truncated", kinds("s13.wks"))
        self.assertIn("truncated", kinds("s15.wpd"))
        self.assertIn("truncated", kinds("s22.000"))
        self.assertIn("truncated", kinds("s29_almost_libra.dat"))


if __name__ == "__main__":
    unittest.main()
