"""M1 EBCDIC descriptor, packed-decimal, and trailer damage matrix."""
import json
import random
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import SAMPLES, check_contract
from deadbits.cli import run as run_cli
from deadbits.formats import ebcdic_dump as ebcdic
from deadbits.engine import salvage_bytes


def packed(value, size):
    digits = str(abs(value)).zfill(size * 2 - 1)
    return bytes.fromhex(digits + ('d' if value < 0 else 'f'))


def synthetic_extract(blocked=False):
    """Independent known-value fixture, including leap day, accents and a debt."""
    expected = [
        {'student_id': '000101', 'name': 'JOSÉ, ANA', 'dob': '1980-02-29',
         'gpa': 3.75, 'credits': 18, 'status': 'A', 'balance': -25.5},
        {'student_id': '000202', 'name': 'LEE, SAM', 'dob': '1979-12-31',
         'gpa': 2.5, 'credits': 21, 'status': 'G', 'balance': 0.0},
        {'student_id': '000303', 'name': 'MÜLLER, EVE', 'dob': '1982-01-01',
         'gpa': 4.0, 'credits': 24, 'status': 'P', 'balance': 120.25},
    ]
    payloads = [('H' + 'RÉSUMÉ EXTRACT'.ljust(20) + '20000229').encode('cp037')]
    for rec in expected:
        payloads.append(
            ('D' + rec['student_id'] + rec['name'].ljust(20)).encode('cp037') +
            packed(int(rec['dob'].replace('-', '')), 5) +
            packed(round(rec['gpa'] * 100), 3) +
            struct.pack('>H', rec['credits']) + rec['status'].encode('cp037') +
            packed(round(rec['balance'] * 100), 4) + b'\x40\x40')
    payloads.append(b'\xe3' + packed(3, 4) + packed(63, 5))
    records = [struct.pack('>H', len(payload) + 4) + b'\0\0' + payload
               for payload in payloads]
    if not blocked:
        return b''.join(records), expected
    blocks = [b''.join(records[:2]), b''.join(records[2:4]), records[4]]
    return b''.join(struct.pack('>H', len(block) + 4) + b'\0\0' + block
                    for block in blocks), expected


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

    def test_independent_known_values_and_printable_cp037(self):
        for blocked in (False, True):
            with self.subTest(blocked=blocked):
                data, expected = synthetic_extract(blocked)
                result = salvage_bytes(data, 'known.000')
                doc = check_contract(self, result, len(data))
                self.assertEqual(doc['format'], 'EBCDIC-DUMP')
                self.assertEqual(doc['status'], 'ok')
                self.assertEqual(doc['records'], expected)
                self.assertEqual(doc['damage'], [])
                self.assertEqual(doc['metadata'], {
                    'title': 'RÉSUMÉ EXTRACT', 'run_date': '2000-02-29',
                    'trailer_count': 3, 'trailer_credits_total': 63})

    def test_vb_first_students_invalid_fields_preserve_block_sibling(self):
        original, expected = synthetic_extract(True)
        for offset in (120, 125, 131, 100, 130):
            # Block 2 first student's DOB/GPA/balance/name/status respectively.
            with self.subTest(offset=offset):
                data = bytearray(original)
                data[offset] = 0xff if offset in (120, 125, 131) else 0
                result = salvage_bytes(bytes(data), 'known.000')
                doc = check_contract(self, result, len(data))
                self.assertEqual(doc['status'], 'partial')
                self.assertEqual(len(doc['records']), 3)
                self.assertEqual(doc['records'][0], expected[0])
                self.assertEqual(doc['records'][2], expected[2])
                self.assertFalse(doc['records'][1]['verified'])
                self.assertEqual(doc['records'][1]['issues'], ['invalid_value'])
                self.assertEqual(self.kinds(doc), ['invalid_value'])

    def test_vb_bad_first_rdw_preserves_intact_sibling(self):
        original, expected = synthetic_extract(True)
        for damaged_offset in (89, 90, 91, 92):
            with self.subTest(offset=damaged_offset):
                data = bytearray(original)
                data[damaged_offset] ^= 1
                doc = salvage_bytes(bytes(data), 'known.000').to_dict()
                self.assertEqual(doc['records'], [expected[0], expected[2]])
                self.assertEqual(self.kinds(doc), ['bad_length'])
                self.assertEqual(doc['damage'][0]['offset'], 89)

    def test_vb_corrupt_first_record_type_preserves_intact_sibling(self):
        original, expected = synthetic_extract(True)
        for kind in range(256):
            if kind == 0xc4:
                continue
            with self.subTest(kind=kind):
                data = bytearray(original)
                data[93] = kind  # Block 2 first student's type; RDWs/BDWs intact.
                result = salvage_bytes(bytes(data), 'known.000')
                doc = check_contract(self, result, len(data))
                self.assertEqual(doc['format'], 'EBCDIC-DUMP')
                self.assertEqual(doc['status'], 'partial')
                self.assertEqual(doc['records'], [expected[0], expected[2]])
                expected_kind = 'bad_length' if kind in (0xc8, 0xe3) else 'unknown_record'
                self.assertEqual(self.kinds(doc), [expected_kind])
                self.assertEqual(doc['damage'][0]['offset'], 89)

    def test_damaged_header_fields_still_dispatch_using_independent_students(self):
        for blocked in (False, True):
            original, expected = synthetic_extract(blocked)
            offset = 4 if blocked else 0
            for field, position, value in (('run_date', offset + 29, 0xf9),
                                           ('title', offset + 5, 0)):
                with self.subTest(blocked=blocked, field=field):
                    data = bytearray(original)
                    data[position] = value
                    doc = salvage_bytes(bytes(data), 'known.000').to_dict()
                    self.assertEqual(doc['format'], 'EBCDIC-DUMP')
                    self.assertEqual(doc['status'], 'partial')
                    self.assertEqual(doc['records'], expected)
                    self.assertIsNone(doc['metadata'][field])
                    self.assertEqual(self.kinds(doc), ['invalid_value'])

    def test_control_characters_null_only_affected_student_field(self):
        original, expected = synthetic_extract()
        for field, position in (('name', 44), ('status', 74)):
            for control in (0, 0x15, 0x25, 0xff):
                with self.subTest(field=field, control=control):
                    data = bytearray(original)
                    data[position] = control
                    doc = salvage_bytes(bytes(data), 'known.000').to_dict()
                    damaged = dict(expected[0], verified=False, issues=['invalid_value'])
                    damaged[field] = None
                    self.assertEqual(doc['records'], [damaged] + expected[1:])
                    self.assertEqual(doc['status'], 'partial')
                    self.assertEqual(self.kinds(doc), ['invalid_value'])

    def test_damaged_header_needs_multiple_coherently_framed_students(self):
        original, _ = synthetic_extract()
        data = bytearray(original)
        data[5] = 0
        candidates = [bytes(data[:33]), bytes(data[:81]), bytes(data[:33]) + bytes(1000)]
        broken = bytearray(data)
        broken[83] = 1  # Corrupt the second student's RDW before two are evidenced.
        candidates.append(bytes(broken))
        broken = bytearray(data)
        broken[2] = 1  # Damaged header content plus descriptor lacks initial evidence.
        candidates.append(bytes(broken))
        for candidate in candidates:
            with self.subTest(data=candidate[:40].hex(), length=len(candidate)):
                self.assertEqual(ebcdic.detect(candidate), 0)
                self.assertEqual(salvage_bytes(candidate, 'unknown.bin').format, 'UNKNOWN')

    def test_detection_evidence_is_bounded_for_large_unrecognized_suffix(self):
        original, _ = synthetic_extract()
        data = bytearray(original[:33])
        data[5] = 0
        data.extend(bytes(2 * 1024 * 1024))
        with patch.object(ebcdic, '_record_end', wraps=ebcdic._record_end) as probe:
            self.assertEqual(ebcdic.detect(bytes(data)), 0)
            self.assertLessEqual(probe.call_count, 20)

    def test_resync_rejects_huge_lengths_before_reading_payloads(self):
        hostile = b'\xff\xff\0\0' * 32768
        with patch.object(ebcdic, '_credible', wraps=ebcdic._credible) as probe:
            self.assertIsNone(ebcdic._next_record(hostile, 0, len(hostile)))
            # None of these 65535-byte lengths describes a known record shape.
            self.assertEqual(probe.call_count, 0)

    def test_cli_dispatch_keeps_students_when_header_date_is_damaged(self):
        data, expected = synthetic_extract(True)
        data = bytearray(data)
        data[33] = 0xf9  # VB header month tens; invalid but framing remains sound.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incoming, outgoing = root / 'in', root / 'out'
            incoming.mkdir()
            (incoming / 'known.000').write_bytes(data)
            report = run_cli(incoming, outgoing)
            doc = json.loads((outgoing / 'known.000.json').read_text(encoding='utf-8'))
            self.assertEqual(doc['format'], 'EBCDIC-DUMP')
            self.assertEqual(doc['records'], expected)
            self.assertEqual(doc['status'], 'partial')
            self.assertEqual(report['files'][0]['records'], 3)

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

    def test_seeded_compound_damage_directly(self):
        rng = random.Random(107105)
        for name in ('s20.000', 's21.000', 's22.000'):
            original = (SAMPLES / name).read_bytes()
            for case in range(128):
                data = bytearray(original)
                for _ in range(rng.randint(1, 4)):
                    pos = rng.randrange(len(data) + 1)
                    operation = rng.randrange(4)
                    if operation == 0:
                        del data[pos:pos + rng.randint(1, 16)]
                    elif operation == 1:
                        data[pos:pos] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 16)))
                    elif operation == 2:
                        stop = min(pos + rng.randint(1, 16), len(data))
                        data[pos:stop] = bytes([rng.randrange(256)]) * (stop - pos)
                    else:
                        del data[pos:]
                with self.subTest(name=name, case=case):
                    res = ebcdic.decode(bytes(data), name)
                    res.size = len(data)
                    doc = check_contract(self, res, len(data))
                    self.assertEqual(set(doc), {'source_file', 'format', 'status', 'metadata', 'records', 'damage'})
                    json.dumps(doc, allow_nan=False)

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
