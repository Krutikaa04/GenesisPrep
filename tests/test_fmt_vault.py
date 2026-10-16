"""VAULT damage matrix (M2-1, M2-2).  Files are built from scratch so every field can be broken on purpose."""
import hashlib
import struct
import unittest

from helpers import SAMPLES, check_contract, salvage_bytes

HDR, ENT = 16, 16


def _xor(buf, key):
    return bytes(b ^ ((key + i) & 0xFF) for i, b in enumerate(buf))


def rle_encode(d):
    out, i = bytearray(), 0
    while i < len(d):
        b, run = d[i], 1
        while i + run < len(d) and d[i + run] == b and run < 255:
            run += 1
        if b == 0x90:
            out += b"\x90\x00" * run
        elif run >= 4:
            out += bytes([b, 0x90, run])
        else:
            out += bytes([b]) * run
        i += run
    return bytes(out)


def build(entries, key=0x21, hflags=0):
    """entries: dicts id,type,flags,name,data (decoded payload) and optional raw (stored payload override)."""
    blocks, names, index = b"", b"", []
    for e in entries:
        data = e["data"]
        fl = e.get("flags", 0)
        stored = e.get("raw")
        if stored is None:
            stored = rle_encode(data) if fl & 1 else data
            stored = _xor(stored, key) if fl & 2 else stored
        block = b"BL" + struct.pack("<H", e["id"]) + stored
        nm = e["name"].encode("latin-1")
        index.append(dict(e, boff=HDR + len(blocks), stored_len=len(block), name_off=len(names), size=len(data)))
        blocks += block
        names += bytes([len(nm) ^ (key if hflags & 1 else 0)]) + _xor(nm, key)
    names_off = HDR + len(blocks)
    index_off = names_off + len(names)
    idx = b"".join(struct.pack("<HBBIIHH", x["id"], x["type"], x.get("flags", 0), x["name_off"], x["boff"],
                               x["stored_len"], x["size"]) for x in index)
    head = b"VLT1" + struct.pack("<HBBII", len(entries), key, hflags, index_off, names_off)
    return head + blocks + names + idx


def patch(data, off, fmt, *vals):
    b = bytearray(data)
    struct.pack_into(fmt, b, off, *vals)
    return bytes(b)


ENTRIES = [
    dict(id=100, type=1, flags=3, name="notes.txt", data=b"Remember: buy chalk. " + b"-" * 30),
    dict(id=101, type=3, flags=0, name="raw.bin", data=bytes(range(20))),
    dict(id=102, type=2, flags=1, name="icon.bmp", data=bytes([4, 4]) + bytes(16)),
]
TEXT = ENTRIES[0]["data"].decode()


class Base(unittest.TestCase):
    def run_(self, data, name="t.dat"):
        res = salvage_bytes(data, name)
        check_contract(self, res, len(data), name)
        return res

    def kinds(self, res):
        return [d["kind"] for d in res.damage]


class VaultBuilt(Base):
    def test_clean_roundtrip(self):
        for hf in (0, 1):
            for key in (0, 1, 0x21, 0xFF):
                res = self.run_(build(ENTRIES, key, hf))
                self.assertEqual((res.format, res.status, res.damage), ("VAULT", "ok", []), (hf, key))
                r = res.records
                self.assertEqual([x["name"] for x in r], ["notes.txt", "raw.bin", "icon.bmp"])
                self.assertEqual(r[0]["text"], TEXT)
                self.assertEqual(r[0]["sha256"], hashlib.sha256(ENTRIES[0]["data"]).hexdigest())
                self.assertEqual((r[2]["width"], r[2]["height"]), (4, 4))
                self.assertTrue(all("verified" not in x for x in r))

    # --- index / pointers -------------------------------------------------------------------------
    def test_index_offset_outside_file(self):
        data = patch(build(ENTRIES), 8, "<I", 10 ** 6)
        res = self.run_(data)
        self.assertEqual(res.status, "failed")
        self.assertIn("index_missing", self.kinds(res))
        self.assertEqual(res.records, [])

    def test_index_offset_inside_header(self):
        res = self.run_(patch(build(ENTRIES), 8, "<I", 4))
        self.assertEqual((res.status, res.records), ("failed", []))

    def test_names_offset_outside_file_is_reported_once(self):
        res = self.run_(patch(build(ENTRIES), 12, "<I", 10 ** 6))
        self.assertEqual(res.status, "partial")
        self.assertEqual(self.kinds(res), ["oob_pointer"])
        self.assertTrue(all(r["name"] is None and r["verified"] is False for r in res.records))
        self.assertEqual(res.records[0]["text"], TEXT)        # content itself is unaffected

    def test_entry_block_offset_out_of_range(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        res = self.run_(patch(data, index_off + ENT + 8, "<I", 10 ** 6))
        self.assertEqual(res.status, "partial")
        bad = [r for r in res.records if r["id"] == 101][0]
        self.assertFalse(bad["verified"])
        self.assertNotIn("sha256", bad)
        self.assertTrue(all("verified" not in r for r in res.records if r["id"] != 101))

    def test_block_id_mismatch(self):
        data = build(ENTRIES)
        boff = HDR + len(b"BL") + 2 + len(_xor(ENTRIES[0]["data"], 0x21)) * 0   # first block starts at 0x10
        bad = patch(data, HDR + 2, "<H", 999)
        res = self.run_(bad)
        first = res.records[0]
        self.assertFalse(first["verified"])
        self.assertIn("oob_pointer", first["issues"])
        self.assertNotIn("text", first)
        self.assertGreater(boff, 0)

    def test_block_overlapping_index_table(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        res = self.run_(patch(data, index_off + 8, "<I", index_off - 4))
        self.assertIn("oob_pointer", self.kinds(res))
        self.assertFalse(res.records[0]["verified"])

    def test_name_offset_outside_names_table(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        res = self.run_(patch(data, index_off + 4, "<I", 5000))
        self.assertIsNone(res.records[0]["name"])
        self.assertFalse(res.records[0]["verified"])

    # --- lengths --------------------------------------------------------------------------------------
    def test_size_field_corrupted_keeps_record_unverified_without_hash(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        for new_size in (0, 1, 50, 52, 53, 40000):   # 51 is the true size
            res = self.run_(patch(data, index_off + 14, "<H", new_size))
            rec = res.records[0]
            self.assertFalse(rec["verified"], new_size)
            self.assertIn("bad_length", rec["issues"])
            self.assertNotIn("sha256", rec)
            self.assertEqual(res.status, "partial")

    def test_stored_length_corrupted(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        for new_len in (3, 10, 4000):
            res = self.run_(patch(data, index_off + ENT + 12, "<H", new_len))
            rec = [r for r in res.records if r["id"] == 101][0]
            self.assertFalse(rec["verified"], new_len)
            self.assertNotIn("sha256", rec)

    # --- truncation / counts -------------------------------------------------------------------------
    def test_truncated_before_index_loses_everything_honestly(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        res = self.run_(data[:index_off - 1])
        self.assertEqual((res.status, res.records), ("failed", []))
        self.assertEqual(self.kinds(res), ["index_missing", "truncated"])

    def test_truncated_inside_index_keeps_complete_entries(self):
        data = build(ENTRIES)
        index_off = struct.unpack_from("<I", data, 8)[0]
        res = self.run_(data[:index_off + ENT + 5])
        self.assertEqual([r["id"] for r in res.records], [100])
        self.assertEqual(res.status, "partial")
        self.assertIn("truncated", self.kinds(res))
        self.assertNotIn("verified", res.records[0])

    def test_count_too_high(self):
        res = self.run_(patch(build(ENTRIES), 4, "<H", 9))
        self.assertEqual([r["id"] for r in res.records], [100, 101, 102])
        self.assertEqual(self.kinds(res), ["count_mismatch"])

    def test_count_too_low(self):
        res = self.run_(patch(build(ENTRIES), 4, "<H", 2))
        self.assertEqual([r["id"] for r in res.records], [100, 101])
        self.assertEqual(self.kinds(res), ["unparsed_bytes"])
        self.assertFalse(res.damage[0]["lossy"])

    def test_count_zero(self):
        res = self.run_(patch(build(ENTRIES), 4, "<H", 0))
        self.assertEqual(res.records, [])

    def test_duplicate_id_is_flagged(self):
        dup = [dict(ENTRIES[0]), dict(ENTRIES[1], id=100)]
        res = self.run_(build(dup))
        self.assertFalse(res.records[1]["verified"])

    # --- facts (M2-2) ---------------------------------------------------------------------------------
    def test_wrong_xor_key_is_not_verified(self):
        """A wrong key leaves lengths intact, so only the plausibility checks can notice it."""
        res = self.run_(patch(build(ENTRIES, 0x21), 6, "<B", 0x77))
        self.assertEqual(res.status, "partial")
        text = [r for r in res.records if r["type"] == "text"][0]
        self.assertFalse(text["verified"])
        self.assertTrue({"invalid_value", "bad_length"} & set(text["issues"]), text["issues"])

    def test_key_error_that_still_looks_like_text_is_a_known_limit(self):
        """key 0x22 instead of 0x21 yields printable garbage: undetectable without a checksum (documented)."""
        res = self.run_(patch(build(ENTRIES, 0x21), 6, "<B", 0x22))
        self.assertNotEqual(res.records[0]["text"], TEXT)

    def test_unknown_entry_type(self):
        data = build([dict(ENTRIES[1], type=9)])
        index_off = struct.unpack_from("<I", data, 8)[0]
        res = self.run_(data)
        self.assertEqual(res.records[0]["type"], "binary")
        self.assertIn("invalid_value", res.records[0]["issues"])
        self.assertFalse(res.damage[0]["lossy"])
        self.assertGreater(index_off, 0)

    def test_header_flag_bits_other_than_bit0_are_ignored(self):
        res = self.run_(build(ENTRIES, 0x21, 0) [:7] + b"\x02" + build(ENTRIES, 0x21, 0)[8:])
        self.assertEqual(res.status, "ok")

    def test_rle_edge_cases(self):
        # 0x90 literal, repeat count 1 (no extra copy), repeat of a long run, escape at the very end
        data = b"A\x90\x00B" + b"C" + bytes([0x90, 1]) + b"D" + bytes([0x90, 5])
        want = b"A\x90BCDDDDD"
        res = self.run_(build([dict(id=1, type=3, flags=1, name="e.bin", data=want, raw=data)]))
        self.assertEqual(res.records[0]["sha256"], hashlib.sha256(want).hexdigest())
        self.assertNotIn("verified", res.records[0])

    def test_rle_dangling_escape_does_not_crash_and_is_unverified(self):
        res = self.run_(build([dict(id=1, type=3, flags=1, name="e.bin", data=b"ABC", raw=b"ABC\x90")]))
        self.assertFalse(res.records[0]["verified"])
        self.assertNotIn("sha256", res.records[0])

    def test_rle_repeat_count_zero_is_literal_escape(self):
        want = b"x\x90y"
        res = self.run_(build([dict(id=1, type=3, flags=1, name="e.bin", data=want, raw=b"x\x90\x00y")]))
        self.assertEqual(res.records[0]["sha256"], hashlib.sha256(want).hexdigest())

    def test_bitmap_hash_covers_dimension_bytes(self):
        res = self.run_(build(ENTRIES))
        self.assertEqual(res.records[2]["sha256"], hashlib.sha256(ENTRIES[2]["data"]).hexdigest())   # assumption

    def test_bitmap_size_not_matching_dimensions_is_flagged(self):
        data = bytes([5, 5]) + bytes(10)          # 5x5 needs 27 bytes
        res = self.run_(build([dict(id=1, type=2, flags=0, name="b.bmp", data=data)]))
        self.assertFalse(res.records[0]["verified"])
        self.assertEqual(res.status, "partial")

    def test_control_characters_in_text_are_flagged(self):
        res = self.run_(build([dict(id=1, type=1, flags=0, name="t.txt", data=b"ok\x01\x02text")]))
        self.assertFalse(res.records[0]["verified"])

    def test_invalid_utf8_text_is_kept_but_unverified(self):
        res = self.run_(build([dict(id=1, type=1, flags=0, name="t.txt", data=b"Sig\x98ned")]))
        rec = res.records[0]
        self.assertFalse(rec["verified"])
        self.assertEqual(rec["issues"], ["invalid_value"])
        self.assertEqual((res.status, [d["kind"] for d in res.damage]), ("partial", ["invalid_value"]))

    def test_valid_non_ascii_utf8_text_stays_verified(self):
        res = self.run_(build([dict(id=1, type=1, flags=0, name="t.txt", data="caf\u00e9".encode())]))
        self.assertEqual((res.status, res.records[0]["text"]), ("ok", "caf\u00e9"))

    def test_tab_newline_cr_in_text_are_fine(self):
        res = self.run_(build([dict(id=1, type=1, flags=0, name="t.txt", data=b"a\tb\r\nc")]))
        self.assertEqual(res.status, "ok")


class VaultSamples(Base):
    def files(self):
        return [SAMPLES / n for n in ("s08.dat", "s09.dat", "s10.dat")]

    def test_every_truncation_gives_a_contract_valid_result_and_never_a_false_verified_record(self):
        for p in self.files():
            raw = p.read_bytes()
            clean = {r["id"]: r for r in salvage_bytes(raw, p.name).records}
            for n in range(len(raw)):
                res = self.run_(raw[:n], p.name)
                for rec in res.records:
                    if rec.get("verified", True):
                        self.assertEqual(rec, clean[rec["id"]], "%s truncated to %d" % (p.name, n))

    def test_every_single_byte_corruption_is_contract_valid(self):
        for p in self.files():
            raw = p.read_bytes()
            for i in range(len(raw)):
                for v in (0, 0xFF, raw[i] ^ 1):
                    b = bytearray(raw)
                    b[i] = v
                    self.run_(bytes(b), p.name)

    def test_verified_records_always_carry_a_hash(self):
        for p in self.files():
            raw = p.read_bytes()
            for i in range(0, len(raw), 3):
                b = bytearray(raw)
                b[i] ^= 0x55
                for rec in self.run_(bytes(b), p.name).records:
                    if rec.get("verified", True):
                        self.assertIn("sha256", rec)

    def test_damaged_text_payload_inside_a_compressed_block_is_never_verified(self):
        # Measured false-verified cases (reports/m3-evaluation.json): size still matched, text was garbage.
        raw = (SAMPLES / "s08.dat").read_bytes()
        flipped = bytearray(raw)
        flipped[153] ^= 0xFF
        zeroed = bytearray(raw)
        zeroed[137:169] = bytes(32)
        for damaged in (flipped, zeroed):
            res = self.run_(bytes(damaged), "s08.dat")
            report = [r for r in res.records if r["name"] == "report.txt"][0]
            self.assertFalse(report["verified"])
            self.assertEqual(res.status, "partial")

    def test_kit_files_still_ok(self):
        for p in self.files():
            res = self.run_(p.read_bytes(), p.name)
            self.assertEqual((res.status, res.damage), ("ok", []), p.name)


if __name__ == "__main__":
    unittest.main()
