"""Independent large EBCDIC V/VB extracts with physical descriptor budgets."""
import json
import struct
import sys
import unittest
from unittest.mock import patch
from helpers import check_contract
from deadbits import _large, engine
from deadbits.formats import ebcdic_dump as ebcdic
from profile_large import profile


def packed(value,size):return bytes.fromhex(str(value).zfill(size*2-1)+"f")
def rdw(payload):return struct.pack(">H",len(payload)+4)+b"\0\0"+payload


def extract(count=12000, blocked=False, headers=1):
    head=rdw(("H"+"KNOWN EXTRACT".ljust(20)+"20000229").encode("cp037"))
    records=[head]*headers
    for i in range(count):
        payload=("D"+str(100000+i)+"KNOWN STUDENT".ljust(20)).encode("cp037")
        payload+=packed(19800229,5)+packed(325,3)+struct.pack(">H",18)+"A".encode("cp037")+packed(1000,4)+b"\x40\x40"
        records.append(rdw(payload))
    records.append(rdw(b"\xe3"+packed(count,4)+packed(18*count,5)))
    if not blocked:return b"".join(records)
    blocks=[b"".join(records[i:i+1000]) for i in range(0,len(records),1000)]
    return b"".join(struct.pack(">H",len(block)+4)+b"\0\0"+block for block in blocks)


def fixtures():
    yield "valid-v",extract()
    yield "valid-vb",extract(blocked=True)
    yield "valid-metadata-heavy",extract(1,headers=65000)
    yield "student-output-pressure",extract(17000)
    head=extract(0)[:33]
    yield "dense-unknown-rdw",head+b"\0\x05\0\0\0"*110000
    bad=bytearray(extract(blocked=True));bad[2]=1
    yield "invalid-bdw",bytes(bad)


class EbcdicLarge(unittest.TestCase):
    def test_v_and_vb_large_students_have_exact_independent_answers(self):
        for blocked in (False,True):
            data=extract(blocked=blocked)
            self.assertGreater(len(data),500000)
            result=engine.salvage_bytes(data,"large.000")
            check_contract(self,result,len(data))
            self.assertEqual((result.format,result.status,result.damage),("EBCDIC-DUMP","ok",[]))
            self.assertEqual(len(result.records),12000)
            for i,rec in enumerate(result.records):
                self.assertEqual(rec,dict(student_id=str(100000+i),name="KNOWN STUDENT",dob="1980-02-29",gpa=3.25,credits=18,status="A",balance=10.0))
            self.assertEqual(result.metadata["trailer_count"],12000)
            self.assertEqual(result.metadata["trailer_credits_total"],216000)
            self.assertEqual(result.to_dict(),engine.salvage_bytes(data,"large.000").to_dict())

    def test_large_metadata_repetition_does_not_allocate_students_from_file_size(self):
        data=extract(1,headers=65000)
        self.assertGreater(len(data),2*1024*1024)
        result=engine.salvage_bytes(data,"metadata.000")
        self.assertEqual((result.status,len(result.records),result.damage),("ok",1,[]))
        self.assertEqual(result.records[0]["student_id"],"100000")

    def test_unsafe_inputs_never_reach_decoder_or_resync(self):
        for name,data in list(fixtures())[3:]:
            with self.subTest(case=name),patch.object(ebcdic,"decode") as decode,patch.object(ebcdic,"_next_record",side_effect=AssertionError("resync")):
                result=engine.salvage_bytes(data,name)
            decode.assert_not_called()
            self.assertEqual((result.format,result.status,result.records),("EBCDIC-DUMP","failed",[]))
            self.assertEqual(result.damage[0]["kind"],"bad_length")
            self.assertTrue(result.damage[0]["lossy"])

    def test_exact_output_work_and_physical_descriptor_budgets(self):
        from deadbits._large_ebcdic import resource_issue
        data=extract(1)
        for name,ceiling in (("MAX_OUTPUT_BYTES",4096+64+1024+64),("MAX_WORK_BYTES",8*len(data)),("MAX_ITEMS",3)):
            with patch.object(_large,name,ceiling):self.assertIsNone(resource_issue(data,"coarse"))
            with patch.object(_large,name,ceiling-1):self.assertIn("budget",resource_issue(data,"coarse"))
        bad=bytearray(data);bad[33:35]=b"\xff\xff"
        self.assertEqual(resource_issue(bytes(bad),"coarse"),"coarse")
        bad=bytearray(extract(1,blocked=True));bad[:2]=b"\xff\xff"
        self.assertEqual(resource_issue(bytes(bad),"coarse"),"coarse")

    def test_exhaustion_stops_before_later_descriptors(self):
        from deadbits._large_ebcdic import resource_issue
        with patch.object(_large,"MAX_OUTPUT_BYTES",4096+64+1024),patch.object(ebcdic,"_record_end",wraps=ebcdic._record_end) as scan:
            self.assertIn("output",resource_issue(extract(100),"coarse"))
        self.assertEqual(scan.call_count,3)


if __name__ == "__main__":
    if sys.argv[1:] == ["--profile-before"]:
        with patch("deadbits._limits._large_resource_issue",side_effect=lambda data,fmt,reason:reason):report=profile(fixtures())
        report["policy"]="Original coarse refusal replay; helpers disabled, decoders unchanged."
        print(json.dumps(report,indent=2,sort_keys=True))
    elif sys.argv[1:] == ["--profile"]:print(json.dumps(profile(fixtures()),indent=2,sort_keys=True))
    else:unittest.main()
