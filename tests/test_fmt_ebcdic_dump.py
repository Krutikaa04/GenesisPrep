"""M1 EBCDIC descriptor, packed-decimal, and trailer damage matrix."""
import random
import struct
import unittest

from helpers import SAMPLES, check_contract
from deadbits.formats import ebcdic_dump as ebcdic
from deadbits.engine import salvage_bytes


def packed(value, size):
    digits = str(abs(value)).zfill(size * 2 - 1)
    return bytes.fromhex(digits + ('d' if value < 0 else 'f'))


class Ebcdic(unittest.TestCase):
    def setUp(self):
        self.data = (SAMPLES / 's20.000').read_bytes()
        self.original = ebcdic.decode(self.data,'s20.000').records
        self.spans=[]
        p=0
        while p<len(self.data):
            end=p+int.from_bytes(self.data[p:p+2],'big')
            self.spans.append((p,end))
            p=end

    def decode(self, data, invariant=True):
        res=ebcdic.decode(bytes(data),'mutation.000')
        res.size=len(data)
        doc=check_contract(self,res,len(data))
        if invariant:
            for rec in doc['records']:
                if rec.get('verified',True) and 'issues' not in rec:
                    self.assertIn(rec,self.original)
        return doc

    def kinds(self,doc):
        return [d['kind'] for d in doc['damage']]

    def test_rdw_length_corruption_salvages_later_records(self):
        a,b=self.spans[2]
        for length in (0,1,4,5,47,49,65535):
            with self.subTest(length=length):
                data=bytearray(self.data);struct.pack_into('>H',data,a,length)
                doc=self.decode(data)
                self.assertEqual(doc['records'],self.original[:1]+self.original[2:])
                self.assertEqual(self.kinds(doc),['bad_length'])

    def test_rdw_reserved_bytes_corruption(self):
        a,b=self.spans[2]
        data=bytearray(self.data);data[a+2]=1
        doc=self.decode(data)
        self.assertEqual(doc['records'],self.original[:1]+self.original[2:])
        self.assertEqual(self.kinds(doc),['bad_length'])

    def test_header_rdw_corruption_still_identified(self):
        for value in (0,1,65535):
            data=bytearray(self.data);struct.pack_into('>H',data,0,value)
            res=salvage_bytes(bytes(data),'mutation.000')
            self.assertEqual(res.format,'EBCDIC-DUMP')
            self.assertEqual(res.records,self.original)
            self.assertEqual([d['kind'] for d in res.damage],['bad_length'])

    def test_bdw_length_corruption(self):
        original=(SAMPLES/'s21.000').read_bytes()
        want=ebcdic.decode(original,'s21.000').records
        for value in (0,1,4,8,84,86,65535):
            with self.subTest(value=value):
                data=bytearray(original);struct.pack_into('>H',data,0,value)
                doc=self.decode(data,invariant=False)
                records=[{k:v for k,v in r.items() if k not in ('verified','issues')} for r in doc['records']]
                self.assertEqual(records,want)
                self.assertIn('bad_length',self.kinds(doc))
                self.assertNotIn('count_mismatch',self.kinds(doc))
                self.assertFalse(doc['records'][0]['verified'])
                self.assertEqual(doc['records'][1:],want[1:])

    def test_bdw_reserved_corruption(self):
        data=bytearray((SAMPLES/'s21.000').read_bytes());data[2]=1
        doc=self.decode(data,invariant=False)
        self.assertEqual(len(doc['records']),5)
        self.assertIn('bad_length',self.kinds(doc))
        self.assertFalse(doc['records'][0]['verified'])

    def test_record_cannot_cross_bdw_boundary(self):
        data=bytearray((SAMPLES/'s21.000').read_bytes())
        # Block 2 ends at 185. Its first RDW must not swallow block 3.
        struct.pack_into('>H',data,89,200)
        doc=self.decode(data,invariant=False)
        self.assertEqual(len(doc['records']),4)
        self.assertIn('bad_length',self.kinds(doc))
        self.assertNotIn('count_mismatch',self.kinds(doc))

    def test_trailer_count_mismatch(self):
        a,b=self.spans[-1]
        for count in (0,4,6,9999999):
            data=bytearray(self.data);data[a+5:a+9]=packed(count,4)
            doc=self.decode(data)
            self.assertEqual(self.kinds(doc),['count_mismatch'])
            self.assertEqual(doc['records'],self.original)

    def test_credits_total_mismatch_marks_all_candidates_unverified(self):
        a,b=self.spans[-1]
        data=bytearray(self.data);data[a+9:a+14]=packed(403,5)
        doc=self.decode(data)
        self.assertEqual(self.kinds(doc),['checksum_mismatch'])
        self.assertTrue(all(not r['verified'] and r['issues']==['checksum_mismatch'] for r in doc['records']))

    def test_truncated_mid_record(self):
        a,b=self.spans[-2]
        for cut in range(a+1,b):
            doc=self.decode(self.data[:cut])
            self.assertEqual(doc['records'],self.original[:-1])
            self.assertEqual(self.kinds(doc),['truncated'])

    def test_truncated_before_and_inside_trailer(self):
        a,b=self.spans[-1]
        for cut in range(a,b):
            doc=self.decode(self.data[:cut])
            self.assertEqual(doc['records'],self.original)
            self.assertEqual(self.kinds(doc),['truncated'])

    def test_truncated_vb_outer_and_inner_reports_one_root(self):
        original=(SAMPLES/'s21.000').read_bytes()
        for cut in (100,120,180,190,275,300,302):
            doc=self.decode(original[:cut],invariant=False)
            self.assertEqual(self.kinds(doc).count('truncated'),1)
            self.assertNotIn('count_mismatch',self.kinds(doc))
            self.assertNotIn('checksum_mismatch',self.kinds(doc))

    def test_invalid_packed_digits_and_sign(self):
        a,b=self.spans[1]
        for offset in (a+5+26,a+5+31,a+5+37):
            for value in (0xfa,0x9a):
                # 0xFA gives invalid digits. Invalid sign is tested separately below.
                data=bytearray(self.data);data[offset]=value
                doc=self.decode(data)
                self.assertIn('invalid_value',self.kinds(doc))
                self.assertFalse(doc['records'][0]['verified'])
        data=bytearray(self.data);data[a+5+40]&=0xf0
        doc=self.decode(data)
        self.assertIsNone(doc['records'][0]['balance'])
        self.assertFalse(doc['records'][0]['verified'])

    def test_negative_balance_sign_d_and_b(self):
        a,b=self.spans[1]
        for sign in (0xd,0xb):
            data=bytearray(self.data);offset=a+5+40;data[offset]=(data[offset]&0xf0)|sign
            doc=self.decode(data,invariant=False)
            self.assertEqual(doc['records'][0]['balance'],-self.original[0]['balance'])
            self.assertEqual(doc['status'],'ok')

    def test_unknown_record_type_skipped(self):
        a,b=self.spans[2]
        data=bytearray(self.data);data[a+4]=0xe7
        doc=self.decode(data)
        self.assertEqual(doc['records'],self.original[:1]+self.original[2:])
        self.assertEqual(self.kinds(doc),['unknown_record'])

    def test_short_trailer_never_calls_packed_on_empty_slice(self):
        a,b=self.spans[-1]
        for size in range(1,10):
            data=self.data[:a]+struct.pack('>H',4+size)+b'\0\0'+self.data[a+4:a+4+size]
            doc=self.decode(data)
            self.assertEqual(self.kinds(doc),['bad_length'])

    def test_invalid_trailer_packed_total(self):
        a,b=self.spans[-1]
        data=bytearray(self.data);data[a+5]=0xff
        doc=self.decode(data)
        self.assertEqual(self.kinds(doc),['invalid_value'])

    def test_invalid_run_date(self):
        data=bytearray(self.data);data[25:33]='19990230'.encode('cp037')
        doc=self.decode(data)
        self.assertIn('invalid_value',self.kinds(doc))
        self.assertIsNone(doc['metadata']['run_date'])

    def test_fixed_length_is_not_guessed_without_a_generator_sample(self):
        payloads=[self.data[a+4:b] for a,b in self.spans]
        unframed=b''.join(payloads)
        fixed=b''.join(p.ljust(44,b'\x40') for p in payloads)
        self.assertEqual(ebcdic.detect(unframed),0)
        self.assertEqual(ebcdic.detect(fixed),0)

    def test_false_positive_h_marker_is_insufficient(self):
        for data in (b'\0\x21\0\0\xc8'+bytes(40),b'\0\0\0\0\xc8',b'H plain text'):
            self.assertEqual(ebcdic.detect(data),0)

    def test_supplied_sample_status_and_totals(self):
        for name,status,count,total in (('s20.000','ok',5,402),('s21.000','ok',5,546),('s22.000','partial',None,None)):
            data=(SAMPLES/name).read_bytes();doc=self.decode(data,invariant=False)
            self.assertEqual(doc['status'],status)
            if count is not None:
                self.assertEqual(doc['metadata']['trailer_count'],count)
                self.assertEqual(doc['metadata']['trailer_credits_total'],total)
            else:
                self.assertEqual(self.kinds(doc),['truncated'])

    def test_direct_decoder_and_packed_never_raise(self):
        self.assertIsNone(ebcdic._packed(b''))
        rng=random.Random(7105)
        for n in range(512):
            data=bytes(rng.randrange(256) for _ in range(n))
            self.decode(data,invariant=False)
        for byte in range(256):
            ebcdic._packed(bytes([byte]))


if __name__=='__main__':
    unittest.main()
