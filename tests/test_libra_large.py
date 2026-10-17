"""Issue #17 LIBRA complete-chain bounds and independent known records."""
import json
import struct
import sys
import unittest
from unittest.mock import patch
from helpers import check_contract
from deadbits import _large, engine
from deadbits.formats import libra98
from test_fmt_libra98 import record_bytes
from profile_large import profile


def fixture(count=8200):
    rows = []
    for i in range(count):
        rec = dict(id=100000+i, title="A"*230, author="", year=1998,
                   price_cents=123, copies=2, isbn="123456789X", checked_out=False,
                   deleted=False, reference_only=False, due_date=None)
        rows.append(record_bytes(rec))
    header = b"LB98" + struct.pack("<BBHHHHH", 2, 0, count, (20<<9)|(1<<5)|2, 0, 16, 7)
    data = header + b"".join(rows)
    return data + b"END!" + struct.pack("<H", sum(data)&65535)


def fixtures():
    good = fixture()
    yield "valid-long-records", good
    yield "output-pressure", fixture(8210)
    bad = bytearray(good); struct.pack_into("<H", bad, 6, 65535)
    yield "hostile-count", bytes(bad)
    bad = bytearray(good); bad[17] = 0
    yield "hostile-length", bytes(bad)


class LibraLarge(unittest.TestCase):
    def test_large_complete_chain_is_recovered_exactly(self):
        data = fixture()
        self.assertGreater(len(data), 2*1024*1024)
        result = engine.salvage_bytes(data, "large.dat")
        check_contract(self, result, len(data))
        self.assertEqual((result.format, result.status, result.damage), ("LIBRA-98", "ok", []))
        self.assertEqual(len(result.records), 8200)
        for i, rec in enumerate(result.records):
            self.assertEqual(rec, dict(id=100000+i, title="A"*230, author="", year=1998,
                             price_cents=123, copies=2, isbn="123456789X", checked_out=False,
                             deleted=False, reference_only=False, due_date=None))
        self.assertEqual(result.to_dict(), engine.salvage_bytes(data, "large.dat").to_dict())

    def test_oversized_or_uncertain_chain_never_reaches_decoder(self):
        for name, data in list(fixtures())[1:]:
            with self.subTest(case=name), patch.object(libra98, "decode") as decode:
                result = engine.salvage_bytes(data, name)
            decode.assert_not_called()
            self.assertEqual((result.format, result.status, result.records), ("LIBRA-98", "failed", []))
            self.assertEqual(result.damage[0]["kind"], "bad_length")
            self.assertTrue(result.damage[0]["lossy"])
            self.assertEqual(result.to_dict()["damage"][0]["offset"], 0)

    def test_exact_output_work_and_count_bounds(self):
        from deadbits._large_libra import resource_issue
        data = fixture(1)
        output = 1536 + 1024 + 4*255
        with patch.object(_large, "MAX_OUTPUT_BYTES", output):
            self.assertIsNone(resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_OUTPUT_BYTES", output-1):
            self.assertIn("output", resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_WORK_BYTES", 8*len(data)):
            self.assertIsNone(resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_WORK_BYTES", 8*len(data)-1):
            self.assertIn("work", resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_ITEMS", 0):
            self.assertIn("item", resource_issue(data, "coarse"))

    def test_budget_stops_before_decoding_later_records_or_repair_candidates(self):
        from deadbits._large_libra import resource_issue
        data = fixture(20)
        with patch.object(_large, "MAX_OUTPUT_BYTES", 1536+2044), patch.object(libra98, "_parse_record", wraps=libra98._parse_record) as parse:
            self.assertIn("output", resource_issue(data, "coarse"))
        self.assertEqual(parse.call_count, 1)
        data = bytearray(fixture(2)); data[16+256] ^= 1
        self.assertEqual(resource_issue(bytes(data), "coarse"), "coarse")


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
