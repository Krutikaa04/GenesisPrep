"""M1 LABLOG damage matrix and independently read byte-level facts."""
import datetime
import json
import math
import random
import struct
import unittest
from unittest import mock

from helpers import SAMPLES, check_contract
from deadbits.formats import lablog
from deadbits.engine import salvage_bytes
from deadbits.util.checksums import crc16_ccitt_false


def header_crc(data):
    data = bytearray(data)
    struct.pack_into('<H', data, 30, crc16_ccitt_false(data[:30]))
    return bytes(data)


def block(typ, payload):
    body = struct.pack('<BH', typ, len(payload)) + payload
    return b'\xb1' + body + struct.pack('<H', crc16_ccitt_false(body))


def independent_crc(data, init=65535):
    value = init
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 65535 if value & 32768 else (value << 1) & 65535
    return value


def known_log(blocks=None, nchan=2):
    """Independent fixture with directly specified calibrated values."""
    table = block(3, struct.pack('<4sff4sff', b'mV', .5, 1., b'ppm', 2., -3.))
    samples = block(1, struct.pack('<HBhhhh', 10, 2, 4, 5, -2, -32768))
    event = block(2, struct.pack('<HBB', 11, 2, 4) + b'test')
    blocks = [table, samples, event] if blocks is None else blocks
    header = struct.pack('<4sBBH16sIH', b'LLOG', 1, nchan, 25, b'TEST LOGGER', 0, len(blocks))
    return header + struct.pack('<H', crc16_ccitt_false(header)) + b''.join(blocks)


KNOWN_RECORDS = [
    {'sample': 10, 'time_ms': 2500, 'values': [3., 7.]},
    {'sample': 11, 'time_ms': 2750, 'values': [0., None]},
]


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
                # The sample count supplies one candidate length and the
                # original stored CRC proves it: no intact sample is lost.
                self.assertEqual(doc['records'], self.original)
                self.assertEqual(self.kinds(doc), ['bad_length'])
                self.assertFalse(doc['damage'][0]['lossy'])

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
        replacement[-1] ^= 1  # Length repair must fail without the original CRC proof.
        data = bytearray(self.data[:87] + replacement + self.data[87:])
        struct.pack_into('<H', data, 28, 8)
        doc = self.decode(header_crc(data))
        self.assertEqual(doc['records'][:4], self.original[:4])
        self.assertTrue(all(not r['verified'] and 'bad_length' in r['issues'] for r in doc['records'][4:]))

    def test_known_fixture_values_and_engine_dispatch(self):
        res = salvage_bytes(known_log(), 'known.bin')
        self.assertEqual(res.format, 'LABLOG')
        self.assertEqual(res.status, 'ok')
        self.assertEqual(res.records, KNOWN_RECORDS)
        self.assertEqual(res.damage, [])
        self.assertEqual(res.metadata['events'], [{'sample': 11, 'severity': 2, 'message': 'test'}])

    def test_crc_proven_table_sample_and_event_length_repair(self):
        original = known_log()
        positions = (32, 62, 79)
        for pos in positions:
            for length in (0, 1, 65535):
                with self.subTest(pos=pos, length=length):
                    data = bytearray(original)
                    struct.pack_into('<H', data, pos + 2, length)
                    res = salvage_bytes(bytes(data), 'known.bin')
                    self.assertEqual(res.records, KNOWN_RECORDS)
                    self.assertEqual(res.metadata['channels'], [{'index': 0, 'unit': 'mV'}, {'index': 1, 'unit': 'ppm'}])
                    self.assertEqual(res.metadata['events'], [{'sample': 11, 'severity': 2, 'message': 'test'}])
                    self.assertEqual([d['kind'] for d in res.damage], ['bad_length'])
                    self.assertFalse(res.damage[0]['lossy'])

    def test_length_repair_requires_original_crc_and_complete_payload(self):
        original = known_log()
        for pos, end in ((32, 62), (62, 79), (79, len(original))):
            data = bytearray(original)
            struct.pack_into('<H', data, pos + 2, 65535)
            data[end - 1] ^= 1
            raw = lablog._block_at(data, pos)
            self.assertIsNone(lablog._repair_length(data, pos, 2, raw))
            self.assertIsNone(lablog._repair_length(original[:end - 1], pos, 2, None))
        # A coherent CRC-valid block with extra payload is not a damaged length.
        table = original[32:62]
        malformed = block(1, struct.pack('<HBhhhh', 10, 2, 4, 5, -2, -32768) + b'x')
        res = lablog.decode(known_log([table, malformed]), 'known.bin')
        self.assertEqual(res.records, [])
        self.assertEqual([d['kind'] for d in res.damage], ['bad_length'])

    def test_bad_header_channel_count_needs_independent_corroboration(self):
        for count in (0, 1, 3, 255):
            data = bytearray(known_log())
            data[5] = count  # Header CRC deliberately remains broken.
            res = salvage_bytes(bytes(data), 'known.bin')
            self.assertEqual([d['kind'] for d in res.damage], ['header_checksum'])
            self.assertEqual([{k: v for k, v in r.items() if k not in ('verified', 'issues')} for r in res.records], KNOWN_RECORDS)
            self.assertTrue(all(r.get('verified') is False and r['issues'] == ['header_checksum'] for r in res.records))
            self.assertEqual(res.metadata['channels'], [{'index': 0, 'unit': 'mV'}, {'index': 1, 'unit': 'ppm'}])
            self.assertTrue(all(e.get('verified') is False and e['issues'] == ['header_checksum'] for e in res.metadata['events']))
        data = bytearray(known_log()); data[5] = 0
        # A CRC-valid zero-channel header must not be silently replaced.
        self.assertEqual(lablog.decode(header_crc(data), 'known.bin').records, [])
        self.assertIsNone(lablog._inferred_channel_count(known_log([known_log()[32:62]])))
        self.assertIsNone(lablog._inferred_channel_count(known_log([known_log()[62:79]])))

    def test_ambiguous_channel_count_is_not_inferred(self):
        original = known_log()
        table3 = block(3, struct.pack('<4sff', b'V', 1., 0.) * 3)
        sample3 = block(1, struct.pack('<HBhhh', 0, 1, 1, 2, 3))
        data = bytearray(known_log([original[32:62], original[62:79], table3, sample3]))
        data[5] = 0
        self.assertIsNone(lablog._inferred_channel_count(data))
        self.assertEqual(lablog.decode(bytes(data), 'known.bin').records, [])

    def test_malformed_table_preserves_historical_unit_provenance(self):
        original = known_log()
        table, samples = original[32:62], original[62:79]
        changed = bytearray(table[4:-2]); changed[:4] = b'degC'
        res = lablog.decode(known_log([table, samples, block(3, b'bad'), block(3, changed)]), 'known.bin')
        self.assertEqual(res.metadata['channels'][0]['unit'], 'degC')
        self.assertTrue(all(r.get('verified') is False and 'invalid_value' in r['issues'] for r in res.records))
        # Without a usable replacement, the original unit list still describes
        # the intact historical samples; only future calibration is unavailable.
        res = lablog.decode(known_log([table, samples, block(3, b'bad')]), 'known.bin')
        self.assertEqual(res.records, KNOWN_RECORDS)
        self.assertEqual(res.metadata['channels'][0]['unit'], 'mV')

    def test_changed_unit_history_is_invalidated_once_per_record(self):
        original = known_log()
        table, samples = original[32:62], original[62:79]
        blocks = [table]
        for index in range(80):
            blocks.append(samples)
            if index % 7 == 0:
                blocks.append(block(3, b'bad'))
            payload = bytearray(table[4:-2])
            payload[:4] = b'V\0\0\0' if index % 2 == 0 else b'mV\0\0'
            blocks.append(block(3, payload))
        original_unverified = lablog.unverified
        invalidations = {}
        def counted_unverified(record, *issues):
            if 'invalid_value' in issues:
                key = id(record)
                invalidations[key] = invalidations.get(key, 0) + 1
            return original_unverified(record, *issues)
        with mock.patch.object(lablog, 'unverified', side_effect=counted_unverified):
            res = lablog.decode(known_log(blocks), 'alternating.bin')
        self.assertEqual(len(res.records), 160)
        self.assertEqual(len(invalidations), len(res.records))
        self.assertEqual(set(invalidations.values()), {1})
        self.assertTrue(all(r.get('verified') is False and r['issues'] == ['invalid_value'] for r in res.records))

    def test_magic_alone_does_not_override_unknown_engine_output(self):
        for data in (b'LLOG', b'LLOG' + bytes(40), b'LLOG this is ordinary text'):
            self.assertEqual(lablog.detect(data), 0.)
            self.assertEqual(salvage_bytes(data, 'text.bin').format, 'UNKNOWN')
        for data in (known_log()[:16], known_log()[:31]):
            self.assertGreaterEqual(lablog.detect(data), .5)
            self.assertEqual(salvage_bytes(data, 'cut.bin').status, 'failed')
        data = bytearray(known_log()); data[4:8] = bytes(4)
        self.assertEqual(salvage_bytes(bytes(data), 'bad-header.bin').format, 'LABLOG')

    def test_recovery_lookahead_crc_work_scales_linearly(self):
        costs = []
        for count in (100, 200):
            # Complete bad-CRC blocks with no later valid block used to trigger
            # a full repeated suffix scan. Count work instead of timing a CPU.
            data = known_log([b'\xb1\xfa\x00\x00\x00\x00'] * count)
            checked = []
            def measured_crc(payload):
                checked.append(len(payload))
                return crc16_ccitt_false(payload)
            with mock.patch.object(lablog, 'crc16_ccitt_false', side_effect=measured_crc):
                lablog.decode(data, 'hostile.bin')
            costs.append((len(checked), sum(checked)))
            self.assertLess(len(checked), 3 * count + 10)
        self.assertLessEqual(costs[1][0], 2 * costs[0][0] + 2)
        self.assertLessEqual(costs[1][1], 2 * costs[0][1] + 30)

    def test_interval_crc_matches_independent_oracle(self):
        vector = b'123456789'
        self.assertEqual(lablog._CRCIndex(vector).crc(0, len(vector)), 0x29b1)
        rng = random.Random(260116)
        data = bytes(rng.randrange(256) for _ in range(70000))
        index = lablog._CRCIndex(data)
        self.assertFalse(index.active)
        for start, end in ((0, 0), (len(data), len(data)), (17, 17), (0, 65538),
                           (len(data) - 65538, len(data))):
            for init in (0, 1, 0x1234, 0xffff):
                self.assertEqual(index.crc(start, end, init), independent_crc(data[start:end], init))
        for _ in range(60):
            start = rng.randrange(len(data) + 1)
            end = rng.randrange(start, min(start + 65538, len(data)) + 1)
            init = rng.randrange(65536)
            self.assertEqual(index.crc(start, end, init), independent_crc(data[start:end], init))
        short = lablog._CRCIndex(b'abc')
        for init in range(65536):
            self.assertEqual(short.crc(0, 3, init), independent_crc(b'abc', init))
        self.assertEqual(index.prefix.itemsize, 2)
        self.assertEqual(len(index.prefix), len(data) + 1)

    def test_overlapping_candidates_have_bounded_crc_work(self):
        for count in (100, 200, 400):
            dense = (b'\xb1\xfa' + struct.pack('<H', 4 * count)) * count + bytes(4 * count + 6)
            repairs = b'\xb1\x01\0\0\0\0' * count
            for label, payload in (('dense markers', dense), ('overlapping repairs', repairs)):
                data = known_log([])[:32] + payload
                work = {'prefix_bytes': 0, 'shift_steps': 0, 'regular_bytes': 0, 'builds': 0}
                original_build, original_shift = lablog._CRCIndex._build, lablog._shift_crc
                def counted_build(index):
                    work['builds'] += 1
                    work['prefix_bytes'] += len(index.data)
                    return original_build(index)
                def counted_shift(value, length):
                    work['shift_steps'] += length.bit_length()
                    return original_shift(value, length)
                def counted_crc(region):
                    work['regular_bytes'] += len(region)
                    return crc16_ccitt_false(region)
                with self.subTest(count=count, kind=label), \
                     mock.patch.object(lablog._CRCIndex, '_build', counted_build), \
                     mock.patch.object(lablog, '_shift_crc', side_effect=counted_shift), \
                     mock.patch.object(lablog, 'crc16_ccitt_false', side_effect=counted_crc):
                    lablog.decode(data, 'overlap.bin')
                self.assertEqual(work['builds'], 1)
                self.assertEqual(work['prefix_bytes'], len(data))
                self.assertLessEqual(work['shift_steps'], 17 * (4 * count + 10))
                self.assertLessEqual(work['regular_bytes'], 2 * len(data) + 6 * count)

    def test_rejected_main_candidates_do_not_copy_overlapping_payloads(self):
        original_probe = lablog._block_at
        for count in (64, 128):
            # Each bad block spans many later blocks, but a nested empty block
            # has an intact CRC and supplies the next boundary. Copying each
            # rejected main payload would repeat 6*count bytes count times.
            bad = b'\xb1\xfa' + struct.pack('<H', 6 * count)
            payload = (bad + block(0xfb, b'')) * count + bytes(6 * count + 6)
            data = known_log([])[:32] + payload
            probes, copied = [], []
            def measured_probe(data, pos, crc_index=None, materialize=True):
                probes.append(materialize)
                return original_probe(data, pos, crc_index, materialize)
            def measured_bytes(value):
                if isinstance(value, memoryview):
                    copied.append(len(value))
                return bytes(value)
            with mock.patch.object(lablog, '_block_at', side_effect=measured_probe), \
                 mock.patch.object(lablog, 'bytes', side_effect=measured_bytes, create=True):
                lablog.decode(data, 'overlapping-main.bin')
            self.assertGreater(len(probes), count)
            self.assertFalse(any(probes))
            self.assertGreaterEqual(len(copied), count)
            self.assertLessEqual(sum(copied), len(data))

    def test_changed_units_mark_historical_samples_unverified(self):
        payload = bytearray(self.blocks[0][3])
        payload[:4] = b'degC'
        data = bytearray(self.data[:87] + block(3, payload) + self.data[87:])
        struct.pack_into('<H', data, 28, 8)
        doc = self.decode(header_crc(data))
        self.assertEqual(doc['metadata']['channels'][0]['unit'], 'degC')
        self.assertTrue(all(not r['verified'] and 'invalid_value' in r['issues'] for r in doc['records'][:4]))
        self.assertEqual(doc['records'][4:], self.original[4:])

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

    def test_seeded_compound_damage_directly(self):
        rng = random.Random(107105)
        for name in ('s05.dat', 's06.dat', 's07.dat'):
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
                    res = lablog.decode(bytes(data), name)
                    res.size = len(data)
                    doc = check_contract(self, res, len(data))
                    self.assertEqual(set(doc), {'source_file', 'format', 'status', 'metadata', 'records', 'damage'})
                    json.dumps(doc, allow_nan=False)

    def test_direct_decoder_never_raises(self):
        rng=random.Random(7103)
        for n in range(512):
            data=bytes(rng.randrange(256) for _ in range(n))
            self.decode(data,invariant=False)


if __name__=='__main__':
    unittest.main()
