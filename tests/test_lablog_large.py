"""Independent large LABLOG events and dense-sample amplification controls."""
import binascii
import json
import struct
import sys
import unittest
from unittest.mock import patch

from helpers import check_contract
from deadbits import _large, engine
from deadbits.formats import lablog
from profile_large import profile


def block(typ, payload):
    raw = struct.pack("<BH", typ, len(payload)) + payload
    return b"\xb1" + raw + struct.pack("<H", binascii.crc_hqx(raw, 65535))


def log(events=11000, dense=False):
    table = block(3, struct.pack("<4sff", b"V", .5, 1.0))
    if dense:
        parts = [table] + [block(1, struct.pack("<HB", (i*250)%65536, 250)+struct.pack("<250h", *([4]*250))) for i in range(600)]
    else:
        sample = block(1, struct.pack("<HBh", 7, 1, 4))
        event = block(2, struct.pack("<HBB", 7, 2, 200) + b"X"*200)
        parts = [table, sample] + [event]*events
    header = struct.pack("<4sBBH16sIH", b"LLOG", 1, 1, 1, b"KNOWN LOGGER", 0, len(parts))
    return header + struct.pack("<H", binascii.crc_hqx(header, 65535)) + b"".join(parts)


def fixtures():
    good = log()
    yield "valid-events", good
    yield "dense-samples", log(dense=True)
    yield "event-output-pressure", log(13000)
    bad = bytearray(good); bad[30] ^= 1
    yield "bad-header-crc", bytes(bad)
    bad = bytearray(good); bad[-1] ^= 1
    yield "bad-block-crc", bytes(bad)


class LablogLarge(unittest.TestCase):
    def test_large_events_and_sample_have_independent_exact_answers(self):
        self.assertEqual(binascii.crc_hqx(b"123456789", 65535), 0x29B1)
        data = log()
        self.assertGreater(len(data), 2*1024*1024)
        result = engine.salvage_bytes(data, "large.log")
        check_contract(self, result, len(data))
        self.assertEqual((result.format, result.status, result.damage), ("LABLOG", "ok", []))
        self.assertEqual(result.records, [{"sample": 7, "time_ms": 70, "values": [3.0]}])
        self.assertEqual(result.metadata["channels"], [{"index": 0, "unit": "V"}])
        self.assertEqual(result.metadata["events"], [{"sample": 7, "severity": 2, "message": "X"*200}]*11000)
        self.assertEqual(result.to_dict(), engine.salvage_bytes(data, "large.log").to_dict())

    def test_amplification_and_crc_damage_refuse_before_decode_or_crc_index(self):
        for name, data in list(fixtures())[1:]:
            with self.subTest(case=name), patch.object(lablog, "decode") as decode, patch.object(lablog._CRCIndex, "_build", side_effect=AssertionError("full CRC index")):
                result = engine.salvage_bytes(data, name)
            decode.assert_not_called()
            self.assertEqual((result.format, result.status, result.records), ("LABLOG", "failed", []))
            self.assertEqual(result.damage[0]["kind"], "bad_length")
            self.assertTrue(result.damage[0]["lossy"])

    def test_exact_budgets_and_physical_count(self):
        from deadbits._large_lablog import resource_issue
        data = log(1)
        output = 4096+64+544+512+800
        with patch.object(_large, "MAX_OUTPUT_BYTES", output):
            self.assertIsNone(resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_OUTPUT_BYTES", output-1):
            self.assertIn("output", resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_WORK_BYTES", 8*len(data)+16-1):
            self.assertIn("work", resource_issue(data, "coarse"))
        with patch.object(_large, "MAX_ITEMS", 4):
            self.assertIn("item", resource_issue(data, "coarse"))
        bad = bytearray(data); struct.pack_into("<H", bad, 28, 65535)
        struct.pack_into("<H", bad, 30, binascii.crc_hqx(bad[:30], 65535))
        self.assertEqual(resource_issue(bytes(bad), "coarse"), "coarse")

    def test_uncertain_framing_does_not_use_length_repair(self):
        from deadbits._large_lablog import resource_issue
        for field, value in ((32, 0), (34, 0), (35, 255)):
            data = bytearray(log(1)); data[field] = value
            with patch.object(lablog, "_repair_length", side_effect=AssertionError("repair")):
                self.assertEqual(resource_issue(bytes(data), "coarse"), "coarse")
        # Exhaust before visiting later payloads; no preflight-sized output list.
        with patch.object(_large, "MAX_OUTPUT_BYTES", 1):
            self.assertIn("output", resource_issue(log(1), "coarse"))


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
