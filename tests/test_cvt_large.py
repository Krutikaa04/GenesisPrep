"""Issue #17 CVT: independent large text and hostile selection controls."""
import json
import struct
import sys
import unittest
from unittest.mock import patch

from helpers import check_contract
from deadbits import _large, engine
from deadbits.formats import cvt
from profile_large import profile


def seq(payload, declared=None):
    data = bytearray(508)
    data[3:19] = b"LARGE".ljust(16, b"\xa0")
    data[21:23] = b"\0\x06"
    data[23:28] = bytes((100, 1, 2, 3, 4))
    blocks = 1 + (len(payload) + 253) // 254
    struct.pack_into("<H", data, 28, blocks if declared is None else declared)
    data[30:58] = b"PRG formatted GEOS file V1.0"
    return bytes(data) + payload


def fixtures():
    yield "valid-seq", seq(b"A" * (254 * 9000))
    header = bytearray(seq(b""))
    header[21] = 1
    struct.pack_into("<H", header, 28, 2 + 40 * 240)
    index = b"\xf0\xfe" * 40 + b"\0\xff" * 87
    yield "valid-vlir", bytes(header) + index + b"A" * (40 * 240 * 254)
    yield "hostile-seq-output", seq(b"A" * (254 * 17000), 0)


class CvtLarge(unittest.TestCase):
    def test_valid_large_seq_text_is_exact_and_deterministic(self):
        data = next(fixtures())[1]
        self.assertGreater(len(data), 2 * 1024 * 1024)
        result = engine.salvage_bytes(data, "large.cvt")
        doc = check_contract(self, result, len(data))
        self.assertEqual((result.format, result.status, result.damage), ("CVT", "ok", []))
        self.assertEqual(result.records, [{"slot": 0, "text": "a" * (254 * 9000)}])
        self.assertEqual(doc, engine.salvage_bytes(data, "large.cvt").to_dict())

    def test_output_budget_refuses_before_decoder_even_with_zero_declaration(self):
        data = list(fixtures())[-1][1]
        with patch.object(cvt, "decode") as decode:
            result = engine.salvage_bytes(data, "hostile.cvt")
        decode.assert_not_called()
        self.assertEqual((result.format, result.status, result.records), ("CVT", "failed", []))
        self.assertEqual(result.damage[0]["kind"], "bad_length")
        self.assertTrue(result.damage[0]["lossy"])
        self.assertEqual(result.to_dict()["damage"][0]["offset"], 0)

    def test_valid_large_vlir_keeps_all_slots_and_exact_text(self):
        data = list(fixtures())[1][1]
        result = engine.salvage_bytes(data, "large-vlir.cvt")
        check_contract(self, result, len(data))
        self.assertEqual((result.status, result.damage), ("ok", []))
        self.assertEqual(result.records, [{"slot": i, "text": "a" * (240 * 254)} for i in range(40)])

    def test_budget_boundaries_and_vlir_selection_use_physical_bytes(self):
        from deadbits._large_cvt import resource_issue
        data = seq(b"A" * 254)
        charge = 1536 + 4 * 254
        with patch.object(_large, "MAX_OUTPUT_BYTES", charge):
            self.assertIsNone(resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_OUTPUT_BYTES", charge - 1):
            self.assertIn("output", resource_issue(data, "coarse"))
        data = bytearray(seq(b"\0" * 254))
        data[21] = 1
        data[508:510] = b"\xff\xfe"
        # A hostile VLIR declaration selects only bytes physically available.
        self.assertIsNone(resource_issue(bytes(data), "coarse"))

    def test_missing_helper_and_exhausted_scan_keep_refusal(self):
        with patch.object(_large.importlib, "import_module", side_effect=ModuleNotFoundError):
            self.assertEqual(_large.resource_issue(b"x", "CVT", "coarse"), "coarse")
        class TooLarge:
            def __len__(self):
                return _large.MAX_SCAN_BYTES + 1
            def __getitem__(self, key):
                raise AssertionError("read past scan budget")
        self.assertIn("safety limit", _large.resource_issue(TooLarge(), "CVT", "coarse"))


if __name__ == "__main__":
    if sys.argv[1:] == ["--profile-before"]:
        with patch("deadbits._limits._large_resource_issue", side_effect=lambda data, fmt, reason: reason):
            report = profile(fixtures())
        report["policy"] = "Original coarse refusal replay; helpers disabled, decoders unchanged."
        print(json.dumps(report, indent=2, sort_keys=True))
    elif sys.argv[1:] == ["--profile"]:
        print(json.dumps(profile(fixtures()), indent=2, sort_keys=True))
    else:
        unittest.main()
