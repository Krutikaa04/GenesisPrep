"""M1 LIBRA damage matrix, semantics, and direct decoder safety."""
import json
import builtins
import random
import struct
import unittest
from unittest import mock

from helpers import SAMPLES, check_contract
from deadbits.formats import libra98
from deadbits.engine import salvage_bytes


KNOWN_RECORDS = [
    {"id": 41, "title": "Café", "author": "Zoë", "year": 1998,
     "price_cents": 1234, "copies": 2, "isbn": "0306406152",
     "checked_out": True, "deleted": False, "reference_only": True, "due_date": "2000-02-29"},
    {"id": 42, "title": "ASCII survives", "author": "Plain", "year": 1970,
     "price_cents": 0, "copies": 0, "isbn": "123456789X",
     "checked_out": False, "deleted": True, "reference_only": False, "due_date": None},
]


def record_bytes(rec, encoding="cp437"):
    """Independent known-value fixture writer; does not call decoder helpers."""
    title, author = rec["title"].encode(encoding), rec["author"].encode(encoding)
    flags = int(rec["checked_out"]) | (int(rec["deleted"]) << 1) | (int(rec["reference_only"]) << 2)
    due = 0
    if rec["due_date"]:
        year, month, day = map(int, rec["due_date"].split("-"))
        due = ((year - 1980) << 9) | (month << 5) | day
    body = (struct.pack("<BI", flags, rec["id"]) + bytes([len(title)]) + title
            + bytes([len(author)]) + author
            + struct.pack("<HHB", rec["year"] - 1500, rec["price_cents"], rec["copies"])
            + rec["isbn"].encode("ascii") + struct.pack("<H", due))
    body += bytes([sum(body) & 255])
    return b"\xa5" + bytes([len(body)]) + body


def known_file(records=KNOWN_RECORDS, encoding="cp437", vendor=b""):
    created = ((1998 - 1980) << 9) | (10 << 5) | 3
    clock = (11 << 11) | (20 << 5) | 11
    header = b"LB98" + struct.pack("<BBHHHHH", 2, int(encoding == "cp1252"), len(records),
                                  created, clock, 16 + len(vendor), 7)
    data = header + vendor + b"".join(record_bytes(r, encoding) for r in records)
    return data + b"END!" + struct.pack("<H", sum(data) & 65535)


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

    def test_stray_trailer_in_garbage_does_not_hide_records(self):
        pos = self.spans[1][0]
        for garbage in (b'END!xx', b'junkEND!xxjunk'):
            data = self.data[:pos] + garbage + self.data[pos:]
            doc = self.decode(file_checksum(data))
            self.assertEqual(doc['records'], self.original)
            self.assertEqual(self.kinds(doc), ['unparsed_bytes'])

    def test_resynchronisation_also_recovers_a_bad_length(self):
        pos = self.spans[1][0]
        data = bytearray(self.data)
        data[pos + 1] = 255
        data = data[:pos] + b'junk' + data[pos:]
        doc = self.decode(file_checksum(data))
        self.assertEqual(doc['records'], self.original)
        self.assertEqual(self.kinds(doc), ['unparsed_bytes', 'bad_length'])

    def test_recovery_never_silently_replaces_undefined_text(self):
        data = bytearray(self.data)
        data[5] = 1  # cp1252 has undefined byte 0x81.
        data[24] = 0x81
        start, end = self.spans[0]
        data[end-1] = sum(data[start+2:end-1]) & 255
        data[17] = 0
        doc = self.decode(file_checksum(data))
        self.assertTrue(all('\ufffd' not in r.get('title', '') or not r.get('verified', True)
                            for r in doc['records']))
        self.assertEqual(doc['records'], self.original[1:])

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

    def test_seeded_compound_damage_directly(self):
        rng = random.Random(107105)
        for name in ('s01.dat', 's02.dat', 's03.dat', 's04.dat', 's29_almost_libra.dat'):
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
                    res = libra98.decode(bytes(data), name)
                    res.size = len(data)
                    doc = check_contract(self, res, len(data))
                    self.assertEqual(set(doc), {'source_file', 'format', 'status', 'metadata', 'records', 'damage'})
                    json.dumps(doc, allow_nan=False)

    def test_direct_decoder_never_raises(self):
        rng = random.Random(7101)
        for n in range(512):
            data = bytes(rng.randrange(256) for _ in range(n))
            res = libra98.decode(data, 'hostile.dat')
            res.size = len(data)
            check_contract(self, res, len(data))


class LibraIndependent(unittest.TestCase):
    """Known-value and end-to-end regressions, independent of kit decoder output."""

    def decode(self, data):
        return check_contract(self, salvage_bytes(data, "independent.bin"), len(data))

    def test_known_values_under_both_code_pages(self):
        for encoding in ("cp437", "cp1252"):
            with self.subTest(encoding=encoding):
                doc = self.decode(known_file(encoding=encoding, vendor=b"LIBSYS/98"))
                self.assertEqual(doc["format"], "LIBRA-98")
                self.assertEqual(doc["status"], "ok")
                self.assertEqual(doc["damage"], [])
                self.assertEqual(doc["records"], KNOWN_RECORDS)
                self.assertEqual(doc["metadata"], {
                    "version": 2, "encoding": encoding, "created": "1998-10-03T11:20:22",
                    "branch_id": 7, "declared_record_count": 2, "data_offset": 25,
                })

    def test_encoding_flag_corruption_taints_only_codec_dependent_text(self):
        mutants = {"cp437": ("Caf‚", "Zo‰"), "cp1252": ("CafΘ", "Zoδ")}
        for encoding, text in mutants.items():
            with self.subTest(encoding=encoding):
                data = bytearray(known_file(encoding=encoding))
                data[5] ^= 1
                doc = self.decode(bytes(data))
                self.assertEqual(doc["status"], "partial")
                self.assertEqual([d["kind"] for d in doc["damage"]], ["checksum_mismatch"])
                self.assertEqual(doc["records"][0], dict(KNOWN_RECORDS[0], title=text[0], author=text[1],
                                                        verified=False, issues=["checksum_mismatch"]))
                self.assertEqual(doc["records"][1], KNOWN_RECORDS[1])

        # The original review reproduction goes through format detection too.
        data = bytearray((SAMPLES / "s03.dat").read_bytes())
        data[5] ^= 1
        records = {r["id"]: r for r in self.decode(bytes(data))["records"]}
        self.assertEqual(records[1004]["title"], "AliceÆs Adventures in Wonderland")
        self.assertFalse(records[1004]["verified"])
        self.assertEqual(records[1023]["title"], "Das Schlo▀")
        self.assertFalse(records[1023]["verified"])
        self.assertEqual(records[1011]["title"], "Walden")
        self.assertNotIn("verified", records[1011])

    def test_unconfirmed_trailer_cannot_verify_non_ascii_text(self):
        data = known_file()
        bad_checksum = data[:-1] + bytes([data[-1] ^ 1])
        for label, mutant, issue in (
                ("trailer-only checksum flip", bad_checksum, "checksum_mismatch"),
                ("missing trailer", data[:-6], "truncated"),
                ("partial marker", data[:-4], "truncated"),
                ("partial checksum", data[:-1], "truncated")):
            with self.subTest(label=label):
                doc = self.decode(mutant)
                self.assertEqual(doc["status"], "partial")
                self.assertEqual([d["kind"] for d in doc["damage"]], [issue])
                # Even unchanged text is uncertain: the same checksum failure
                # could have come from the header's encoding bit instead.
                self.assertEqual(doc["records"][0], dict(KNOWN_RECORDS[0], verified=False, issues=[issue]))
                self.assertEqual(doc["records"][1], KNOWN_RECORDS[1])

    def test_ascii_text_stays_independent_of_corrupt_encoding_flag(self):
        records = [dict(KNOWN_RECORDS[1], id=73)]
        data = bytearray(known_file(records))
        data[5] ^= 1
        doc = self.decode(bytes(data))
        self.assertEqual(doc["records"], records)
        self.assertEqual([d["kind"] for d in doc["damage"]], ["checksum_mismatch"])

    def test_in_bounds_offset_recovered_only_with_full_chain_proof(self):
        data = known_file()
        second = 16 + len(record_bytes(KNOWN_RECORDS[0]))
        for offset in (17, second, second + 1, len(data) - 6, len(data)):
            with self.subTest(offset=offset):
                mutant = bytearray(data)
                struct.pack_into("<H", mutant, 12, offset)
                doc = self.decode(bytes(mutant))
                self.assertEqual(doc["records"], [
                    dict(KNOWN_RECORDS[0], verified=False, issues=["checksum_mismatch"]), KNOWN_RECORDS[1]])
                self.assertEqual([d["kind"] for d in doc["damage"]], ["invalid_value", "checksum_mismatch"])
                self.assertEqual(doc["damage"][0]["offset"], 12)
                self.assertFalse(doc["damage"][0]["lossy"])
                self.assertEqual(doc["metadata"]["data_offset"], offset)

        # Extended headers must also survive natural pointer corruption.
        data = known_file(vendor=b"LIBSYS/98\x00END!xx")
        mutant = bytearray(data)
        struct.pack_into("<H", mutant, 12, struct.unpack_from("<H", data, 12)[0] + 1)
        doc = self.decode(bytes(mutant))
        self.assertEqual([r["id"] for r in doc["records"]], [41, 42])
        self.assertEqual([d["kind"] for d in doc["damage"]], ["invalid_value", "checksum_mismatch"])

    def test_vendor_record_bytes_are_not_reclassified_as_data(self):
        vendor = b"VENDOR" + record_bytes(dict(KNOWN_RECORDS[1], id=777))
        data = known_file(vendor=vendor)
        doc = self.decode(data)
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["records"], KNOWN_RECORDS)
        self.assertEqual(doc["damage"], [])

        # Even a trailer suggesting the vendor record's offset is insufficient:
        # that chain has three records, contradicting the declared count of two.
        mutant = bytearray(data)
        declared = struct.unpack_from("<H", data, 12)[0]
        fake_start = 22
        stored = (sum(data[:-6]) - sum(declared.to_bytes(2, "little"))
                  + sum(fake_start.to_bytes(2, "little"))) & 65535
        struct.pack_into("<H", mutant, len(mutant) - 2, stored)
        doc = self.decode(bytes(mutant))
        self.assertEqual([r["id"] for r in doc["records"]], [41, 42])
        self.assertEqual([d["kind"] for d in doc["damage"]], ["checksum_mismatch"])

    def test_recomputed_or_compound_offset_damage_is_not_guessed(self):
        data = bytearray(known_file())
        struct.pack_into("<H", data, 12, 17)
        recomputed = file_checksum(data)
        doc = self.decode(recomputed)
        self.assertEqual(doc["records"], [KNOWN_RECORDS[1]])
        self.assertEqual([d["kind"] for d in doc["damage"]], ["unparsed_bytes", "count_mismatch"])
        # A second error removes the independent evidence for the earlier start.
        data[-1] ^= 0x80
        doc = self.decode(bytes(data))
        self.assertEqual(doc["records"], [KNOWN_RECORDS[1]])
        self.assertNotIn("invalid_value", [d["kind"] for d in doc["damage"]])

    def test_ambiguous_checksum_valid_offset_chains_are_not_guessed(self):
        blank = dict(KNOWN_RECORDS[1], author="")
        outer_first = record_bytes(dict(blank, id=5001, title="p" * 157))
        inner_first = record_bytes(dict(blank, id=5003, title="a" * 53))
        inner_last = record_bytes(dict(blank, id=5004, title="b" * 79))
        # Two real, overlapping chains: [16, 200] and [271, 351]. Both have
        # two checksum-valid records ending at 457. Offsets 16 and 271 have
        # equal byte sums, so the file checksum cannot distinguish them.
        title = b"q" * 63 + inner_first + inner_last[:87]
        self.assertEqual(len(title), 230)
        body = bytearray(struct.pack("<BI", 0, 5002) + b"\xe6" + title + inner_last[87:])
        body[6] = (body[-1] - sum(body[:-1]) + body[6]) & 255
        outer_last = b"\xa5\xff" + body
        header = bytearray(known_file()[:16])
        struct.pack_into("<H", header, 12, 300)
        payload = bytes(header) + outer_first + outer_last
        self.assertEqual(len(payload), 457)
        stored = (sum(payload) - sum(header[12:14]) + 16) & 65535
        data = payload + b"END!" + struct.pack("<H", stored)
        self.assertTrue(libra98._valid_chain(data, 16, 457, 2, "cp437"))
        self.assertTrue(libra98._valid_chain(data, 271, 457, 2, "cp437"))
        self.assertIsNone(libra98._recover_data_offset(data, 300, 2, "cp437"))
        doc = self.decode(data)
        self.assertEqual(doc["records"], [dict(blank, id=5004, title="b" * 79)])
        self.assertNotIn("invalid_value", [d["kind"] for d in doc["damage"]])

    def test_stray_end_before_verified_final_trailer_reports_only_gap(self):
        for garbage in (b"END!xx", b"END!xxEND!yy", b"END!xxjunkEND!zz"):
            with self.subTest(garbage=garbage):
                data = known_file()
                mutant = file_checksum(data[:-6] + garbage + data[-6:])
                doc = self.decode(mutant)
                self.assertEqual(doc["records"], KNOWN_RECORDS)
                self.assertEqual(doc["status"], "partial")
                self.assertEqual([d["kind"] for d in doc["damage"]], ["unparsed_bytes"])
                self.assertEqual(doc["damage"][0]["offset"], len(data) - 6)
                self.assertIn(str(len(garbage)), doc["damage"][0]["detail"])

    def test_repeated_damage_has_linear_checksum_work(self):
        for count in (64, 512, 4096):
            records = [dict(KNOWN_RECORDS[1], id=i) for i in range(count)]
            valid = known_file(records)
            damaged = valid[:16] + b"".join(b"\xa5\x00" + record_bytes(r) for r in records) + valid[-6:]
            damaged = file_checksum(damaged)
            measured = [0]

            def counted_sum(values, *args, **kwargs):
                measured[0] += len(values)
                return builtins.sum(values, *args, **kwargs)

            with self.subTest(count=count), mock.patch.object(libra98, "sum", counted_sum, create=True):
                doc = self.decode(damaged)
                self.assertEqual(doc["records"], records)
                self.assertEqual([d["kind"] for d in doc["damage"]], ["bad_length"] * count)
                # Count bytes processed by checksum sums, independent of CPU
                # speed. Re-summing each previous prefix exceeds this bound.
                self.assertLessEqual(measured[0], 12 * len(damaged))


if __name__ == '__main__':
    unittest.main()
