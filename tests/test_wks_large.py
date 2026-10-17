"""Independent large WKS labels/metadata and hostile cell/damage density."""
import json
import struct
import sys
import unittest
from unittest.mock import patch
from helpers import check_contract
from deadbits import _large, engine
from deadbits.formats import wks
from profile_large import profile


def record(op, payload=b""):
    return struct.pack("<HH", op, len(payload))+payload


def labels(count=36):
    return record(0, b"\x04\x04") + b"".join(record(15, struct.pack("<BHH",255,0,i)+b"'"+b"A"*60000+b"\0") for i in range(count)) + record(1)


def metadata():
    return record(0,b"\x04\x04") + record(11,b"\0"*24)*18000 + record(13,struct.pack("<BHHh",255,0,0,77)) + record(1)


def fixtures():
    good = labels()
    yield "valid-labels", good
    yield "valid-metadata", metadata()
    yield "dense-unknown-opcodes", record(0,b"\x04\x04")+record(250)*110000+record(1)
    yield "label-output-pressure", labels(72)
    bad = bytearray(good); bad[60016] = 1
    yield "bad-label-boundary", bytes(bad)


class WksLarge(unittest.TestCase):
    def test_large_labels_are_exact_and_deterministic(self):
        data = labels()
        self.assertGreater(len(data), 2*1024*1024)
        result = engine.salvage_bytes(data,"large.wks")
        check_contract(self,result,len(data))
        self.assertEqual((result.format,result.status,result.damage),("WKS","ok",[]))
        self.assertEqual(result.records,[dict(cell="A%d"%(i+1),col=0,row=i,type="label",alignment="left",value="A"*60000) for i in range(36)])
        self.assertEqual(result.to_dict(),engine.salvage_bytes(data,"large.wks").to_dict())

    def test_sparse_output_metadata_is_not_charged_as_dense_cells(self):
        data=metadata()
        result=engine.salvage_bytes(data,"metadata.wks")
        self.assertEqual((result.status,result.damage),("ok",[]))
        self.assertEqual(result.records,[dict(cell="A1",col=0,row=0,type="integer",value=77)])

    def test_hostile_or_uncertain_inputs_never_reach_decoder_or_resync(self):
        for name,data in list(fixtures())[2:]:
            with self.subTest(case=name),patch.object(wks,"decode") as decode,patch.object(wks,"_resync",side_effect=AssertionError("resync")):
                result=engine.salvage_bytes(data,name)
            decode.assert_not_called()
            self.assertEqual((result.format,result.status,result.records),("WKS","failed",[]))
            self.assertEqual(result.damage[0]["kind"],"bad_length")
            self.assertTrue(result.damage[0]["lossy"])

    def test_inclusive_output_work_items_and_unknown_damage_accounting(self):
        from deadbits._large_wks import resource_issue
        data=record(0,b"\x04\x04")+record(13,struct.pack("<BHHh",255,0,0,77))+record(1)
        for name,ceiling in (("MAX_OUTPUT_BYTES",4096+1024+4*7),("MAX_WORK_BYTES",4*len(data)),("MAX_ITEMS",3)):
            with patch.object(_large,name,ceiling):
                self.assertIsNone(resource_issue(data,"coarse"))
            with patch.object(_large,name,ceiling-1):
                self.assertIn("budget",resource_issue(data,"coarse"))
        damage=record(0,b"\x04\x04")+record(250)*4+record(1)
        with patch.object(_large,"MAX_OUTPUT_BYTES",4096+512*3):
            self.assertIn("output",resource_issue(damage,"coarse"))

    def test_repeated_assignments_are_charged_and_exhaustion_stops_the_scan(self):
        from deadbits._large_wks import resource_issue
        cell=record(13,struct.pack("<BHHh",255,0,0,77))
        data=record(0,b"\x04\x04")+cell*100+record(1)
        with patch.object(_large,"MAX_OUTPUT_BYTES",4096+1052),patch.object(wks,"_strict_record",wraps=wks._strict_record) as scan:
            self.assertIn("output",resource_issue(data,"coarse"))
        self.assertEqual(scan.call_count,3) # BOF, first assignment, rejected second assignment


if __name__ == "__main__":
    if sys.argv[1:] == ["--profile-before"]:
        with patch("deadbits._limits._large_resource_issue",side_effect=lambda data,fmt,reason:reason):report=profile(fixtures())
        report["policy"]="Original coarse refusal replay; helpers disabled, decoders unchanged."
        print(json.dumps(report,indent=2,sort_keys=True))
    elif sys.argv[1:] == ["--profile"]:print(json.dumps(profile(fixtures()),indent=2,sort_keys=True))
    else:unittest.main()
