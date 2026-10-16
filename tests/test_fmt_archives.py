"""PAK/WAD directory isolation, ambiguity and deterministic resource bounds."""
import hashlib
import random
import struct
import unittest
from unittest.mock import patch

from helpers import SAMPLES, check_contract, salvage_bytes
from deadbits.formats import _archive, pak, wad
from deadbits.model import Result


def archive(module, payload=b"abcdefgh", entries=None, magic=None):
    """Independent layout writer; entry offsets are absolute byte positions."""
    entries = entries if entries is not None else [("FIRST", 12, len(payload))]
    directory = bytearray()
    for name, offset, size in entries:
        if isinstance(name, str):
            name = name.encode("latin-1")
        if module is pak:
            directory.extend(struct.pack("<56sII", name, offset, size))
        else:
            directory.extend(struct.pack("<II8s", offset, size, name))
    start = 12 + len(payload)
    if module is pak:
        header = struct.pack("<4sII", magic or b"PACK", start, len(directory))
    else:
        header = struct.pack("<4sII", magic or b"PWAD", len(entries), start)
    return header + payload + directory


def kinds(result):
    return [entry["kind"] for entry in result.damage]


class ArchiveHardening(unittest.TestCase):
    def decode(self, module, data):
        result = module.decode(data, "archive.bin")
        result.size = len(data)
        check_contract(self, result, len(data), module.NAME)
        return result

    def test_official_samples_stay_complete_and_hash_exact_bytes(self):
        for module, filename, count in [(pak, "s24.pak", 4), (wad, "s23.wad", 7)]:
            data = (SAMPLES / filename).read_bytes()
            result = self.decode(module, data)
            self.assertEqual(result.status, "ok")
            self.assertEqual(len(result.records), count)
            self.assertEqual(result.damage, [])
            for record in result.records:
                start, size = record["offset"], record["size"]
                self.assertEqual(record["sha256"], hashlib.sha256(data[start:start + size]).hexdigest())
                self.assertNotIn("verified", record)

    def test_huge_declared_count_is_bounded_by_physical_directory(self):
        for module in (pak, wad):
            data = bytearray(archive(module))
            struct.pack_into("<I", data, 8 if module is pak else 4, 0xFFFFFFFF)
            result = self.decode(module, data)
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.records), 1)
            self.assertIn("count_mismatch", kinds(result))
            self.assertGreaterEqual(module.detect(data), 0.5)
            self.assertEqual(salvage_bytes(data, "huge").format, module.NAME)

    def test_directory_entry_budget_is_explicit_and_keeps_original_count(self):
        entries = [("ENTRY%d" % i, 12 + i, 1) for i in range(5)]
        for module in (pak, wad):
            data = archive(module, entries=entries)
            with patch.object(_archive, "MAX_ENTRIES", 2):
                result = self.decode(module, data)
            self.assertEqual(len(result.records), 2)
            self.assertEqual(result.status, "partial")
            self.assertEqual(kinds(result), ["bad_length"])
            self.assertTrue(result.damage[0]["lossy"])
            self.assertIn("safety budget", result.damage[0]["detail"])
            count = result.metadata["declared_entries" if module is pak else "lump_count"]
            self.assertEqual(count, 5)

    def test_duplicate_names_keep_both_and_flag_ambiguity(self):
        for module in (pak, wad):
            data = archive(module, entries=[("SAME", 12, 3), ("SAME", 15, 3)])
            result = self.decode(module, data)
            self.assertEqual(len(result.records), 2)
            self.assertEqual(result.status, "partial")
            self.assertEqual(kinds(result), ["invalid_value"])
            self.assertFalse(result.damage[0]["lossy"])
            for rec in result.records:
                self.assertFalse(rec["verified"])
                self.assertEqual(rec["issues"], ["invalid_value"])
                self.assertIn("sha256", rec)

    def test_overlapping_payloads_keep_both_hashes_with_honesty(self):
        for module in (pak, wad):
            data = archive(module, entries=[("ONE", 12, 5), ("TWO", 15, 5)])
            result = self.decode(module, data)
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.records), 2)
            self.assertEqual(kinds(result), ["invalid_value"])
            self.assertFalse(result.damage[0]["lossy"])
            for rec, payload in zip(result.records, (b"abcde", b"defgh")):
                self.assertEqual(rec["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertFalse(rec["verified"])

    def test_overlap_sweep_handles_nested_and_out_of_order_ranges(self):
        entries = [("LATE", 22, 4), ("OUTER", 12, 12), ("SMALL", 14, 2),
                   ("CLEAR", 28, 2), ("INNER", 18, 2)]
        for module in (pak, wad):
            data = archive(module, b"x" * 20, entries)
            result = self.decode(module, data)
            for index in (0, 1, 2, 4):
                self.assertFalse(result.records[index]["verified"])
            self.assertNotIn("verified", result.records[3])
            self.assertEqual(kinds(result), ["invalid_value"])

    def test_overlap_sweep_matches_independent_pairwise_oracle(self):
        rng = random.Random(317)
        for _ in range(100):
            spans = [(rng.randrange(50), rng.randrange(12)) for _ in range(20)]
            result = Result("probe", "WAD", "ok")
            result.records = [{"name": "E%d" % i} for i in range(len(spans))]
            entries = [(i * 16, (start, start + length)) for i, (start, length) in enumerate(spans)]
            _archive.note_ambiguities(result, entries)
            expected = {i for i, (a, length) in enumerate(spans) if length and
                        any(j != i and other and a < b + other and a + length > b
                            for j, (b, other) in enumerate(spans))}
            found = {i for i, rec in enumerate(result.records) if rec.get("verified") is False}
            self.assertEqual(found, expected)

    def test_dense_nested_overlap_has_one_warning_and_linear_marking(self):
        count = 10_000
        result = Result("nested", "WAD", "ok")
        result.records = [{"name": "E%d" % i} for i in range(count)]
        entries = [(i * 16, (i, 2 * count - i)) for i in range(count)]
        original = _archive.unverified
        with patch.object(_archive, "unverified", wraps=original) as mark:
            _archive.note_ambiguities(result, entries)
        self.assertEqual(mark.call_count, count)
        self.assertEqual(len(result.damage), 1)
        self.assertTrue(all(rec["verified"] is False for rec in result.records))

    def test_adjacent_payloads_and_zero_byte_markers_do_not_overlap(self):
        entries = [("ONE", 12, 4), ("TWO", 16, 4), ("MARKER", 15, 0)]
        for module in (pak, wad):
            result = self.decode(module, archive(module, entries=entries))
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.damage, [])

    def test_zero_byte_entries_have_known_empty_hash_without_dereferencing_offset(self):
        empty = hashlib.sha256(b"").hexdigest()
        for module in (pak, wad):
            for offset in (0, 5, 12, 20, 0xFFFFFFFF):
                with self.subTest(format=module.NAME, offset=offset):
                    result = self.decode(module, archive(module, entries=[("ZERO", offset, 0)]))
                    self.assertEqual(result.status, "ok")
                    self.assertEqual(result.records, [{"name": "ZERO", "offset": offset, "size": 0,
                                                       "sha256": empty}])

    def test_bad_entry_isolated_from_valid_sibling(self):
        for module in (pak, wad):
            data = archive(module, entries=[("BROKEN", 0xFFFFFFFF, 8), ("GOOD", 12, 8)])
            result = self.decode(module, data)
            self.assertEqual(len(result.records), 2)
            self.assertFalse(result.records[0]["verified"])
            self.assertNotIn("sha256", result.records[0])
            self.assertEqual(result.records[0]["issues"], ["oob_pointer"])
            self.assertEqual(result.records[1]["sha256"], hashlib.sha256(b"abcdefgh").hexdigest())
            self.assertNotIn("verified", result.records[1])

    def test_payload_cannot_consume_header_or_directory_bytes(self):
        for module in (pak, wad):
            # payload occupies 12..19, directory starts at 20.
            for offset, size in ((0, 1), (11, 2), (19, 2), (20, 1), (0xFFFFFFFF, 1)):
                with self.subTest(format=module.NAME, offset=offset):
                    result = self.decode(module, archive(module, entries=[("BAD", offset, size)]))
                    self.assertEqual(kinds(result), ["oob_pointer"])
                    self.assertNotIn("sha256", result.records[0])
                    self.assertFalse(result.records[0]["verified"])

    def test_out_of_file_directory_reports_index_missing(self):
        for module in (pak, wad):
            data = bytearray(archive(module))
            struct.pack_into("<I", data, 4 if module is pak else 8, 0xFFFFFFFF)
            result = self.decode(module, data)
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.records, [])
            self.assertEqual(kinds(result), ["index_missing", "truncated"])

    def test_directory_inside_header_reports_index_missing(self):
        for module in (pak, wad):
            data = bytearray(archive(module))
            struct.pack_into("<I", data, 4 if module is pak else 8, 4)
            result = self.decode(module, data)
            self.assertEqual(result.status, "failed")
            self.assertEqual(kinds(result), ["index_missing"])

    def test_complete_entry_boundary_count_damage_has_single_root_kind(self):
        for module in (pak, wad):
            entries = [("ONE", 12, 4), ("TWO", 16, 4)]
            data = archive(module, entries=entries)[:-module.ENTRY_LEN]
            result = self.decode(module, data)
            self.assertEqual(kinds(result), ["count_mismatch"])
            self.assertEqual(len(result.records), 1)

    def test_partial_directory_entry_truncation_does_not_add_count_mismatch(self):
        for module in (pak, wad):
            data = archive(module, entries=[("ONE", 12, 4), ("TWO", 16, 4)])[:-1]
            result = self.decode(module, data)
            self.assertEqual(kinds(result), ["truncated"])
            self.assertEqual(len(result.records), 1)

    def test_pak_nonmultiple_directory_length_is_reported(self):
        data = bytearray(archive(pak))
        struct.pack_into("<I", data, 8, pak.ENTRY_LEN + 1)
        result = self.decode(pak, data)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(kinds(result), ["bad_length"])
        self.assertEqual(result.status, "partial")

    def test_bytes_after_directory_report_exact_boundary(self):
        for module in (pak, wad):
            original = archive(module)
            result = self.decode(module, original + b"extra")
            self.assertEqual(kinds(result), ["unparsed_bytes"])
            self.assertEqual(result.damage[0]["offset"], len(original))
            self.assertFalse(result.damage[0]["lossy"])
            self.assertEqual(result.status, "partial")

    def test_empty_archive_has_no_phantom_entry(self):
        for module in (pak, wad):
            data = archive(module, b"", [])
            result = self.decode(module, data)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.records, [])
            self.assertEqual(result.damage, [])
            self.assertEqual(module.detect(data), 1.0)

    def test_iwad_and_pwad_variants_supported(self):
        for magic in (b"IWAD", b"PWAD"):
            data = archive(wad, magic=magic)
            self.assertEqual(wad.detect(data), 1.0)
            result = self.decode(wad, data)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.metadata["wad_type"], magic.decode("ascii"))

    def test_invalid_magic_variants_never_claim_archive(self):
        for module in (pak, wad):
            for magic in (b"pack", b"WAD2", b"WAD3", b"\xff\xff\xff\xff", b"PACK" if module is wad else b"PWAD"):
                data = archive(module, magic=magic)
                self.assertEqual(module.detect(data), 0.0)
                result = self.decode(module, data)
                self.assertEqual(result.status, "failed")
                self.assertEqual(kinds(result), ["invalid_value"])

    def test_bare_magic_and_incoherent_headers_are_not_detection_proof(self):
        for module, magic in ((pak, b"PACK"), (wad, b"PWAD")):
            for data in (magic, magic + b"\0" * 7, magic + b"\xff" * 8, magic + b"\0" * 40):
                self.assertEqual(module.detect(data), 0.0)

    def test_names_ignore_bytes_after_first_nul(self):
        for module in (pak, wad):
            result = self.decode(module, archive(module, entries=[(b"OK\0\xff\x01", 12, 8)]))
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.records[0]["name"], "OK")

    def test_empty_and_control_corrupt_names_are_unverified(self):
        for module in (pak, wad):
            for name in (b"", b"bad\x01", b"bad\x81"):
                result = self.decode(module, archive(module, entries=[(name, 12, 8)]))
                self.assertEqual(result.status, "partial")
                self.assertEqual(kinds(result), ["invalid_value"])
                self.assertFalse(result.records[0]["verified"])
                self.assertIn("sha256", result.records[0])

    def test_exact_range_aliases_hash_only_once_without_payload_copies(self):
        entries = [("E%d" % i, 12, 8) for i in range(400)]
        native = hashlib.sha256
        seen = []

        def measured(payload):
            self.assertIsInstance(payload, memoryview)
            seen.append(len(payload))
            return native(payload)

        for module in (pak, wad):
            seen.clear()
            with patch.object(_archive.hashlib, "sha256", side_effect=measured):
                result = self.decode(module, archive(module, entries=entries))
            self.assertEqual(seen, [8])
            self.assertEqual(len(result.records), len(entries))
            self.assertTrue(all("sha256" in rec for rec in result.records))
            self.assertEqual(kinds(result), ["invalid_value"])

    def test_unique_overlapping_ranges_cannot_exhaust_hash_work(self):
        entries = [("E%d" % i, 12 + i, 2048) for i in range(60)]
        native = hashlib.sha256
        total = []

        def measured(payload):
            total.append(len(payload))
            return native(payload)

        for module in (pak, wad):
            data = archive(module, b"x" * 4096, entries)
            total.clear()
            with patch.object(_archive.hashlib, "sha256", side_effect=measured):
                result = self.decode(module, data)
            self.assertLessEqual(sum(total), _archive.HASH_WORK_FACTOR * len(data))
            self.assertEqual(len(result.records), len(entries))
            omitted = [rec for rec in result.records if "sha256" not in rec]
            self.assertTrue(omitted)
            self.assertTrue(all(rec["verified"] is False and "bad_length" in rec["issues"] for rec in omitted))
            budgets = [d for d in result.damage if "hash safety budget" in d["detail"]]
            self.assertEqual(len(budgets), 1)
            self.assertTrue(budgets[0]["lossy"])
            self.assertEqual(result.status, "partial")

    def test_exhausted_hash_budget_still_reuses_prior_proven_alias(self):
        entries = [("FIRST", 12, 2048), ("SECOND", 13, 2048), ("ALIAS", 12, 2048)]
        for module in (pak, wad):
            data = archive(module, b"x" * 4096, entries)
            with patch.object(_archive, "HASH_WORK_FACTOR", 0.5):
                result = self.decode(module, data)
            self.assertIn("sha256", result.records[0])
            self.assertNotIn("sha256", result.records[1])
            self.assertEqual(result.records[2]["sha256"], result.records[0]["sha256"])

    def test_direct_decoders_never_raise_on_damaged_bytes(self):
        rng = random.Random(309)
        for module, filename in ((pak, "s24.pak"), (wad, "s23.wad")):
            data = (SAMPLES / filename).read_bytes()
            for end in range(len(data) + 1):
                self.decode(module, data[:end])
            for _ in range(200):
                changed = bytearray(data)
                for _ in range(rng.randrange(1, 5)):
                    changed[rng.randrange(len(changed))] = rng.randrange(256)
                self.decode(module, changed)
            for size in (0, 1, 4, 11, 12, 20, 256):
                self.decode(module, bytes(rng.randrange(256) for _ in range(size)))


if __name__ == "__main__":
    unittest.main()
