"""M1 LABLOG damage matrix and independently read byte-level facts."""
import datetime
import json
import math
import random
import struct
import unittest

from helpers import SAMPLES, check_contract
from deadbits.formats import lablog
from deadbits.util.checksums import crc16_ccitt_false


def header_crc(data):
    data = bytearray(data)
    struct.pack_into('<H', data, 30, crc16_ccitt_false(data[:30]))
    return bytes(data)


def block(typ, payload):
    body = struct.pack('<BH', typ, len(payload)) + payload
    return b'\xb1' + body + struct.pack('<H', crc16_ccitt_false(body))


class Lablog(unittest.TestCase):
    def setUp(self):
        self.data = (SAMPLES / 's05.dat').read_bytes()
        self.original = lablog.decode(self.data, 's05.dat').records
        self.blocks = []
        p = 32
        while p < len(self.data):
            t,b,e,c = lablog._block_at(self.data,p)
            self.blocks.append((p,e,t,b))
            p=e

    def decode(self, data, invariant=True):
        res = lablog.decode(bytes(data), 'mutation.dat')
        res.size = len(data)
        doc = check_contract(self, res, len(data))
        json.dumps(doc, allow_nan=False)
        if invariant:
            for rec in doc['records']:
                if rec.get('verified', True) and 'issues' not in rec:
                    self.assertIn(rec, self.original)
        return doc

    def kinds(self, doc):
        return [d['kind'] for d in doc['damage']]

    def test_block_crc_flip_retains_unverified_samples(self):
        a,b,_,_ = self.blocks[1]
        data=bytearray(self.data);data[b-1]^=1
        doc=self.decode(data)
        self.assertEqual(len(doc['records']),len(self.original))
        self.assertEqual(self.kinds(doc),['crc_mismatch'])
        self.assertTrue(all(not r['verified'] for r in doc['records'][:4]))
        self.assertEqual(doc['records'][4:],self.original[4:])

    def test_calibration_crc_propagates(self):
        data=bytearray(self.data);data[61]^=1
        doc=self.decode(data)
        self.assertTrue(all(not r['verified'] and 'crc_mismatch' in r['issues'] for r in doc['records']))

    def test_header_crc_propagates(self):
        data=bytearray(self.data);data[30]^=1
        doc=self.decode(data)
        self.assertEqual(self.kinds(doc),['header_checksum'])
        self.assertTrue(all('header_checksum' in r['issues'] for r in doc['records']))
        self.assertTrue(all('header_checksum' in e['issues'] for e in doc['metadata']['events']))

    def test_length_corruption_resynchronises(self):
        a,b,_,_ = self.blocks[1]
        for length in (0,1,18,20,255,65535):
            with self.subTest(length=length):
                data=bytearray(self.data);struct.pack_into('<H',data,a+2,length)
                doc=self.decode(data)
                self.assertIn('bad_length',self.kinds(doc))
                self.assertNotIn('count_mismatch',self.kinds(doc))
                self.assertEqual([{k:v for k,v in r.items() if k not in ('verified','issues')} for r in doc['records']],self.original[4:])
                self.assertTrue(all(not r['verified'] for r in doc['records']))

    def test_unknown_block_type(self):
        a,b,_,payload=self.blocks[1]
        doc=self.decode(self.data[:a]+block(0xfa,payload)+self.data[b:])
        self.assertEqual(self.kinds(doc),['unknown_record'])
        self.assertEqual(doc['records'],self.original[4:])

    def test_truncated_data_block_dropped_even_with_complete_rows(self):
        a,b,_,_ = self.blocks[1]
        for cut in range(a+1,b):
            doc=self.decode(self.data[:cut])
            self.assertEqual(self.kinds(doc),['truncated'])
            self.assertEqual(doc['records'],[])

    def test_declared_count_high_and_low(self):
        for count in (0,6,8,65535):
            data=bytearray(self.data);struct.pack_into('<H',data,28,count)
            doc=self.decode(header_crc(data))
            self.assertEqual(self.kinds(doc),['count_mismatch'])
            self.assertEqual(doc['records'],self.original)

    def test_missing_channel_table_never_substitutes_raw_values(self):
        data=bytearray(self.data[:32]+self.data[62:]);struct.pack_into('<H',data,28,6)
        doc=self.decode(header_crc(data))
        self.assertTrue(all(r['values']==[None,None] and not r['verified'] for r in doc['records']))
        self.assertIn('invalid_value',self.kinds(doc))
        self.assertEqual(doc['metadata']['channels'],[])

    def test_two_channel_tables_latest_applies_to_later_samples(self):
        # Repeating an identical table is structurally safe, but the policy is explicit.
        data=bytearray(self.data[:62]+self.data[32:62]+self.data[62:]);struct.pack_into('<H',data,28,8)
        doc=self.decode(header_crc(data))
        self.assertEqual(doc['records'],self.original)
        self.assertEqual(self.kinds(doc),['invalid_value'])

    def test_malformed_replacement_clears_previous_calibration(self):
        data=bytearray(self.data[:87]+block(3,b'bad')+self.data[87:]);struct.pack_into('<H',data,28,8)
        doc=self.decode(header_crc(data))
        self.assertEqual(doc['records'][:4],self.original[:4])
        self.assertTrue(all(not r['verified'] and r['values']==[None,None] for r in doc['records'][4:]))
        self.assertTrue(all('bad_length' in r['issues'] for r in doc['records'][4:]))

    def test_skipped_replacement_table_taints_later_calibration(self):
        replacement = bytearray(self.data[32:62])
        struct.pack_into('<H', replacement, 2, 65535)
        data = bytearray(self.data[:87] + replacement + self.data[87:])
        struct.pack_into('<H', data, 28, 8)
        doc = self.decode(header_crc(data))
        self.assertEqual(doc['records'][:4], self.original[:4])
        self.assertTrue(all(not r['verified'] and 'bad_length' in r['issues'] for r in doc['records'][4:]))

    def test_zero_channels_rejected(self):
        data=bytearray(self.data);data[5]=0
        doc=self.decode(header_crc(data))
        self.assertEqual(doc['status'],'failed')
        self.assertEqual(doc['records'],[])
        self.assertEqual(self.kinds(doc),['invalid_value'])

    def test_nonfinite_calibration_cannot_emit_nan_or_infinity(self):
        for value in (math.nan, math.inf, -math.inf):
            payload=bytearray(self.blocks[0][3]);struct.pack_into('<f',payload,4,value)
            doc=self.decode(self.data[:32]+block(3,payload)+self.data[62:])
            self.assertIn('invalid_value',self.kinds(doc))
            self.assertTrue(all(r['values'][0] is None and not r['verified'] for r in doc['records']))

    def test_bad_sample_and_event_lengths(self):
        for index in (1,3):
            a,b,typ,payload=self.blocks[index]
            doc=self.decode(self.data[:a]+block(typ,payload[:-1])+self.data[b:])
            self.assertEqual(self.kinds(doc),['bad_length'])

    def test_event_crc_failure_marked_in_metadata(self):
        data=bytearray(self.data);data[self.blocks[3][1]-1]^=1
        doc=self.decode(data)
        self.assertFalse(doc['metadata']['events'][0]['verified'])
        self.assertEqual(doc['metadata']['events'][0]['issues'],['crc_mismatch'])

    def test_header_truncation(self):
        for cut in range(32):
            doc=self.decode(self.data[:cut])
            self.assertEqual(doc['status'],'failed')
            self.assertEqual(self.kinds(doc),['truncated'])

    def test_s06_s07_byte_level_facts_not_organizer_goldens(self):
        # These facts are independently read from intact header/event fields.
        for name,nchan,interval,seconds,first_event in (
            ('s06.dat',3,1000,0x06e6635a,(9,0,'Operator note')),
            ('s07.dat',3,250,0x07ff3fce,(8,0,'Operator note')),
        ):
            data=(SAMPLES/name).read_bytes();doc=self.decode(data,invariant=False)
            self.assertEqual(doc['metadata']['sample_interval_ms'],interval)
            expected=(datetime.datetime(1990,1,1)+datetime.timedelta(seconds=seconds)).isoformat()+'Z'
            self.assertEqual(doc['metadata']['start_time_utc'],expected)
            self.assertEqual(len(doc['metadata']['channels']),nchan)
            event=doc['metadata']['events'][0]
            self.assertEqual((event['sample'],event['severity'],event['message']),first_event)
            self.assertTrue(all(r['time_ms']==r['sample']*interval for r in doc['records']))
            if name=='s06.dat':
                self.assertEqual(doc['status'],'ok')
                self.assertTrue(any(None in r['values'] for r in doc['records']))
            else:
                self.assertEqual(doc['status'],'partial')
                self.assertEqual([r['sample'] for r in doc['records'] if not r.get('verified',True)],list(range(9,15)))

    def test_direct_decoder_never_raises(self):
        rng=random.Random(7103)
        for n in range(512):
            data=bytes(rng.randrange(256) for _ in range(n))
            self.decode(data,invariant=False)


if __name__=='__main__':
    unittest.main()
