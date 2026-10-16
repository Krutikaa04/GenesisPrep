"""CVT damage matrix and PETSCII checks (M2-5)."""
import struct
import unittest

from helpers import SAMPLES, check_contract, salvage_bytes

BLK = 254
SIGNATURE = b"PRG formatted GEOS file V1.0"


def pet(text):
    """ASCII -> PETSCII (lower/upper set): lower-case letters are 0x41-0x5A, upper-case 0xC1-0xDA."""
    out = bytearray()
    for ch in text:
        c = ord(ch)
        if ch == "\n":
            out.append(0x0D)
        elif "a" <= ch <= "z":
            out.append(c - 0x20)
        elif "A" <= ch <= "Z":
            out.append(c + 0x80)
        else:
            out.append(c)
    return bytes(out)


def pad(b, n):
    return b + b"\0" * (n - len(b))


def block0(name="Notes", structure=0, declared=3, geos=7, stamp=(91, 3, 14, 9, 30)):
    nm = pet(name)[:16] + b"\xA0" * (16 - len(name))
    head = b"\x83" + b"\x00\x00" + nm + b"\x00\x00" + bytes([structure, geos]) + bytes(stamp) \
        + struct.pack("<H", declared) + SIGNATURE
    return pad(head, BLK)


def info(cls="Text Class", author="Ann", desc="a note"):
    return pad(pad(pet(cls), 20) + pad(pet(author), 20) + pet(desc) + b"\0", BLK)


def seq(text, declared=None):
    body = pet(text)
    nblocks = max(1, -(-len(body) // BLK))
    return block0(declared=1 + nblocks if declared is None else declared) + info() + pad(body, nblocks * BLK)


def vlir(records, declared=None, index_override=None):
    """records: {slot: text}; slot data is stored in slot order."""
    index, data = bytearray(BLK), b""
    for s in range(127):
        index[2 * s], index[2 * s + 1] = 0, 0xFF
    total = 0
    for slot, text in sorted(records.items()):
        raw = pet(text)
        nb = -(-len(raw) // BLK)
        index[2 * slot], index[2 * slot + 1] = nb, len(raw) - (nb - 1) * BLK
        data += pad(raw, nb * BLK)
        total += nb
    if index_override:
        for k, v in index_override.items():
            index[k] = v
    return block0(structure=1, declared=2 + total if declared is None else declared) + info() + bytes(index) + data


class Base(unittest.TestCase):
    def run_(self, data, name="t.cvt"):
        res = salvage_bytes(data, name)
        check_contract(self, res, len(data), name)
        return res

    def kinds(self, res):
        return [d["kind"] for d in res.damage]


class CvtBuilt(Base):
    def test_clean_seq(self):
        res = self.run_(seq("Hello World 123\nline two"))
        self.assertEqual((res.format, res.status, res.damage), ("CVT", "ok", []))
        self.assertEqual(res.records, [{"slot": 0, "text": "Hello World 123\nline two"}])
        m = res.metadata
        self.assertEqual((m["name"], m["structure"], m["geos_type"], m["modified"], m["class_name"], m["author"],
                          m["description"], m["declared_blocks"]),
                         ("Notes", "seq", 7, "1991-03-14T09:30", "Text Class", "Ann", "a note", 2))

    def test_clean_vlir_keeps_slot_numbers(self):
        res = self.run_(vlir({0: "first", 5: "x" * 300, 126: "last"}))
        self.assertEqual(res.status, "ok")
        self.assertEqual([(r["slot"], len(r["text"])) for r in res.records], [(0, 5), (5, 300), (126, 4)])

    # --- PETSCII ---------------------------------------------------------------------------------------
    def test_petscii_digits_punctuation_case_and_cr(self):
        res = self.run_(seq("Mixed Case, digits 0123456789 & punct !\"#$%'()*+,-./:;<=>?@[]\nnext"))
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.records[0]["text"], "Mixed Case, digits 0123456789 & punct !\"#$%'()*+,-./:;<=>?@[]\nnext")

    def test_shifted_space_in_text_is_a_space(self):
        data = block0(declared=2) + info() + pad(b"\x41\xA0\x42", BLK)
        self.assertEqual(self.run_(data).records[0]["text"], "a b")

    def test_graphics_bytes_become_replacement_char_and_are_unverified(self):
        data = block0(declared=2) + info() + pad(b"\x41\x42\xC0\x7F\x43\x44", BLK)
        res = self.run_(data)
        self.assertIn("\ufffd", res.records[0]["text"])
        self.assertFalse(res.records[0]["verified"])
        self.assertEqual(self.kinds(res), ["invalid_value"])
        self.assertEqual(res.status, "partial")

    # --- block counts -----------------------------------------------------------------------------------
    def test_seq_declared_blocks_too_high_is_truncation(self):
        res = self.run_(seq("hello", declared=9))
        self.assertEqual(self.kinds(res), ["truncated"])
        self.assertFalse(res.records[0]["verified"])

    def test_seq_declared_blocks_too_low_reports_lossy_excess(self):
        res = self.run_(seq("x" * 300, declared=2))          # one data block declared, two present
        self.assertEqual(self.kinds(res), ["unparsed_bytes"])
        self.assertTrue(res.damage[0]["lossy"])
        self.assertFalse(res.records[0]["verified"])
        self.assertEqual(len(res.records[0]["text"]), 254)

    def test_vlir_declared_wrong_but_index_and_file_agree_keeps_records_verified(self):
        for declared in (2, 3, 50, 1000):
            res = self.run_(vlir({0: "abc", 2: "def"}, declared=declared))
            self.assertEqual(self.kinds(res), ["count_mismatch"], declared)
            self.assertFalse(res.damage[0]["lossy"])
            self.assertTrue(all(r.get("verified", True) for r in res.records))
            self.assertEqual([r["text"] for r in res.records], ["abc", "def"])

    def test_vlir_index_disagrees_with_file_and_header_marks_records_unverified(self):
        data = vlir({0: "a" * 300, 1: "b" * 10})                 # slot 0 needs 2 blocks
        res = self.run_(data.replace(b"", b"")[:2 * BLK] + bytes([1]) + data[2 * BLK + 1:])   # index says 1 block
        self.assertIn("count_mismatch", self.kinds(res))
        self.assertTrue(all(not r.get("verified", True) for r in res.records))

    # --- truncation ----------------------------------------------------------------------------------------
    def test_truncated_inside_directory_block(self):
        res = self.run_(seq("hello")[:100])
        self.assertEqual((res.status, res.records), ("failed", []))

    def test_truncated_inside_info_block(self):
        res = self.run_(seq("hello")[:BLK + 100])
        self.assertIn("index_missing", self.kinds(res))
        self.assertIsNone(res.metadata["class_name"])

    def test_truncated_inside_seq_data_block(self):
        res = self.run_(seq("x" * 500)[:2 * BLK + 100 + BLK])
        self.assertIn("truncated", self.kinds(res))
        self.assertFalse(res.records[0]["verified"])

    def test_truncated_inside_vlir_record_keeps_earlier_records(self):
        data = vlir({0: "first", 3: "y" * 600})
        res = self.run_(data[:-100])
        by_slot = {r["slot"]: r for r in res.records}
        self.assertNotIn("verified", by_slot[0])
        self.assertFalse(by_slot[3]["verified"])

    def test_truncated_before_vlir_index(self):
        res = self.run_(vlir({0: "abc"})[:2 * BLK + 10])
        self.assertIn("index_missing", self.kinds(res))
        self.assertEqual(res.records, [])

    # --- VLIR index entries ----------------------------------------------------------------------------------
    def test_unused_slot_encodings_00_and_ff_are_both_skipped(self):
        data = vlir({0: "a"}, index_override={2 * 4: 0, 2 * 4 + 1: 0})
        res = self.run_(data)
        self.assertEqual(res.status, "ok")
        self.assertEqual([r["slot"] for r in res.records], [0])

    def test_zero_blocks_with_a_byte_count_is_a_corrupted_index_entry(self):
        res = self.run_(vlir({0: "a", 1: "b"}, index_override={2 * 7: 0, 2 * 7 + 1: 33}))
        self.assertIn("invalid_value", self.kinds(res))
        self.assertTrue(all(not r.get("verified", True) for r in res.records))

    def test_last_block_byte_count_zero_or_over_254(self):
        for bad in (0, 255, 200 + 55):
            res = self.run_(vlir({0: "abc"}, index_override={1: bad}))
            self.assertFalse(res.records[0]["verified"], bad)
            self.assertIn("bad_length", res.records[0]["issues"])

    def test_block_count_beyond_file(self):
        res = self.run_(vlir({0: "abc"}, index_override={0: 100}))
        self.assertIn("truncated", self.kinds(res))
        self.assertFalse(res.records[0]["verified"])

    def test_vlir_slot_full_254_bytes(self):
        res = self.run_(vlir({0: "z" * 254, 1: "w" * 255}))
        self.assertEqual([len(r["text"]) for r in res.records], [254, 255])
        self.assertEqual(res.status, "ok")

    # --- header facts -----------------------------------------------------------------------------------------
    def test_invalid_structure_byte(self):
        data = bytearray(seq("hello"))
        data[0x15] = 9
        res = self.run_(bytes(data))
        self.assertIn("invalid_value", self.kinds(res))
        self.assertEqual(res.metadata["structure"], "seq")

    def test_invalid_timestamp_is_null_not_guessed(self):
        data = bytearray(seq("hello"))
        data[0x18] = 13                                           # month 13
        res = self.run_(bytes(data))
        self.assertIsNone(res.metadata["modified"])
        self.assertEqual(self.kinds(res), ["invalid_value"])


class CvtSamples(Base):
    def files(self):
        return [SAMPLES / "s18.cvt", SAMPLES / "s19.cvt"]

    def test_kit_files_ok(self):
        for p in self.files():
            res = self.run_(p.read_bytes(), p.name)
            self.assertEqual((res.status, res.damage), ("ok", []), p.name)

    def test_every_truncation_never_yields_a_false_verified_record(self):
        for p in self.files():
            raw = p.read_bytes()
            clean = {r["slot"]: r for r in salvage_bytes(raw, p.name).records}
            for n in range(len(raw)):
                for r in self.run_(raw[:n], p.name).records:
                    if r.get("verified", True):
                        self.assertEqual(r, clean[r["slot"]], "%s truncated to %d" % (p.name, n))

    def test_every_single_byte_corruption_is_contract_valid(self):
        for p in self.files():
            raw = p.read_bytes()
            for i in range(len(raw)):
                for v in (0, 0xFF, raw[i] ^ 1):
                    b = bytearray(raw)
                    b[i] = v
                    self.run_(bytes(b), p.name)

    def test_vlir_index_byte_flips_are_never_silent(self):
        raw = (SAMPLES / "s19.cvt").read_bytes()
        clean = salvage_bytes(raw, "s19.cvt").records
        for i in range(2 * BLK, 3 * BLK):
            for v in (0, 1, 7, 0xFF, raw[i] ^ 0x80):
                b = bytearray(raw)
                b[i] = v
                res = self.run_(bytes(b), "s19.cvt")
                if v != raw[i] and res.records != clean:
                    self.assertNotEqual(res.status, "ok", "index byte %d -> %d" % (i - 2 * BLK, v))


if __name__ == "__main__":
    unittest.main()
