"""M1 LIBRA damage matrix, semantics, and direct decoder safety."""
import random
import struct
import unittest

from helpers import SAMPLES, check_contract
from deadbits.formats import libra98


def file_checksum(data):
    data = bytearray(data)
    end = data.rfind(b"END!")
    struct.pack_into("<H", data, end + 4, sum(data[:end]) & 0xffff)
    return bytes(data)


class Libra(unittest.TestCase):
    def setUp(self):
        self.data = (SAMPLES / "s01.dat").read_bytes()
        self.original = libra98.decode(self.data, "s01.dat").records
        self.spans = []
        pos = 16
        while self.data[pos:pos + 1] == b"\xa5":
            end = pos + 2 + self.data[pos + 1]
            self.spans.append((pos, end))
            pos = end

    def decode(self, data):
        res = libra98.decode(bytes(data), "mutation.dat")
        res.size = len(data)
        doc = check_contract(self, res, len(data))
        for rec in doc['records']:
            if rec.get('verified', True) and 'issues' not in rec:
                self.assertIn(rec, self.original)
        return doc

    def kinds(self, doc):
        return [d['kind'] for d in doc['damage']]

    def test_wrong_record_length(self):
        for length in (0, 1, self.data[17] - 1, self.data[17] + 1, 255):
            with self.subTest(length=length):
                data = bytearray(self.data)
                data[17] = length
                doc = self.decode(file_checksum(data))
                self.assertEqual(doc['records'], self.original)
                self.assertEqual(self.kinds(doc), ['bad_length'])

    def test_record_checksum_flip(self):
        data = bytearray(self.data)
        data[self.spans[0][1] - 1] ^= 1
        doc = self.decode(file_checksum(data))
        self.assertFalse(doc['records'][0]['verified'])
        self.assertEqual(doc['records'][1:], self.original[1:])
        self.assertEqual(self.kinds(doc), ['checksum_mismatch'])

    def test_trailer_checksum_flip(self):
        data = bytearray(self.data)
        data[-1] ^= 1
        doc = self.decode(data)
        self.assertEqual(doc['records'], self.original)
        self.assertEqual(self.kinds(doc), ['checksum_mismatch'])
        self.assertEqual(doc['status'], 'partial')

    def test_complete_header_count_high_and_low(self):
        for count in (0, 4, 6, 65535):
            with self.subTest(count=count):
                data = bytearray(self.data)
                struct.pack_into('<H', data, 6, count)
                doc = self.decode(file_checksum(data))
                self.assertEqual(doc['records'], self.original)
                self.assertEqual(self.kinds(doc), ['count_mismatch'])

    def test_truncated_header(self):
        for cut in range(16):
            doc = self.decode(self.data[:cut])
            self.assertEqual(doc['status'], 'failed')
            self.assertEqual(self.kinds(doc), ['truncated'])

    def test_truncated_extended_header(self):
        data = (SAMPLES / 's03.dat').read_bytes()[:30]
        doc = self.decode(data)
        self.assertEqual(doc['status'], 'failed')
        self.assertIn('truncated', self.kinds(doc))
        self.assertNotIn('count_mismatch', self.kinds(doc))
        self.assertEqual(doc['records'], [])

    def test_truncated_record_only_fully_read_id(self):
        start, end = self.spans[-1]
        for cut in range(start + 1, end):
            doc = self.decode(self.data[:cut])
            self.assertEqual(self.kinds(doc), ['truncated'])
            self.assertEqual(doc['records'][:4], self.original[:4])
            if cut >= start + 7:
                self.assertEqual(doc['records'][4:], [dict(id=self.original[-1]['id'], verified=False, issues=['truncated'])])
            else:
                self.assertEqual(len(doc['records']), 4)

    def test_truncated_trailer_suppresses_count_noise(self):
        for cut in range(len(self.data) - 6, len(self.data)):
            data = bytearray(self.data[:cut])
            struct.pack_into('<H', data, 6, 65535)
            doc = self.decode(data)
            self.assertEqual(self.kinds(doc), ['truncated'])
            self.assertEqual(doc['records'], self.original)

    def test_data_offset_out_of_bounds_and_before_header(self):
        for offset in (0, 15, len(self.data) + 1, 65535):
            data = bytearray(self.data)
            struct.pack_into('<H', data, 12, offset)
            doc = self.decode(file_checksum(data))
            self.assertIn('oob_pointer', self.kinds(doc))
            self.assertEqual(doc['records'], self.original)

    def test_garbage_between_records(self):
        pos = self.spans[1][0]
        doc = self.decode(file_checksum(self.data[:pos] + b'garbage' + self.data[pos:]))
        self.assertEqual(doc['records'], self.original)
        self.assertEqual(self.kinds(doc), ['unparsed_bytes'])

    def test_zeroed_record_resynchronises(self):
        start, end = self.spans[1]
        doc = self.decode(file_checksum(self.data[:start] + bytes(end-start) + self.data[end:]))
        self.assertEqual(doc['records'], self.original[:1] + self.original[2:])
        self.assertIn('unparsed_bytes', self.kinds(doc))

    def test_duplicate_ids_retained_and_flagged(self):
        start, end = self.spans[0]
        data = bytearray(self.data[:end] + self.data[start:end] + self.data[end:])
        struct.pack_into('<H', data, 6, 6)
        doc = self.decode(file_checksum(data))
        self.assertEqual(len(doc['records']), 6)
        self.assertEqual(doc['records'][0]['id'], doc['records'][1]['id'])
        self.assertFalse(doc['records'][0]['verified'])
        self.assertFalse(doc['records'][1]['verified'])
        self.assertEqual(self.kinds(doc), ['invalid_value'])

    def test_bytes_after_trailer(self):
        doc = self.decode(self.data + b'junk')
        self.assertEqual(doc['records'], self.original)
        self.assertEqual(self.kinds(doc), ['unparsed_bytes'])
        self.assertFalse(doc['damage'][0]['lossy'])

    def test_deleted_reference_and_extended_header_semantics(self):
        for name in ('s02.dat', 's03.dat'):
            data = (SAMPLES / name).read_bytes()
            doc = libra98.decode(data, name).to_dict()
            self.assertEqual(doc['status'], 'ok')
            self.assertTrue(doc['records'])
            if name == 's02.dat':
                self.assertTrue(any(r['deleted'] for r in doc['records']))
                self.assertTrue(any(r['reference_only'] for r in doc['records']))
            else:
                self.assertEqual(doc['metadata']['data_offset'], 40)
                self.assertEqual(doc['metadata']['encoding'], 'cp1252')

    def test_unknown_version_is_unverified(self):
        data = bytearray(self.data)
        data[4] = 3
        doc = self.decode(file_checksum(data))
        self.assertEqual(self.kinds(doc), ['unknown_record'])
        self.assertTrue(all(not r['verified'] for r in doc['records']))

    def test_invalid_isbn_and_due_date(self):
        for offset, value in ((self.spans[0][1]-13, 0xff), (self.spans[0][1]-3, 0x20)):
            data = bytearray(self.data)
            data[offset] = value
            a,b = self.spans[0]
            data[b-1] = sum(data[a+2:b-1]) & 255
            doc = self.decode(file_checksum(data))
            self.assertIn('invalid_value', self.kinds(doc))
            self.assertFalse(doc['records'][0]['verified'])

    def test_direct_decoder_never_raises(self):
        rng = random.Random(7101)
        for n in range(512):
            data = bytes(rng.randrange(256) for _ in range(n))
            res = libra98.decode(data, 'hostile.dat')
            res.size = len(data)
            check_contract(self, res, len(data))


if __name__ == '__main__':
    unittest.main()
