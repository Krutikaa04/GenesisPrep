"""Preflight refuses unbounded legacy accumulators before decoding any payload."""
import struct
import unittest
from unittest.mock import patch

from helpers import SAMPLES
from deadbits import _limits


def vault_aliases(count, payload, flags=0, declared_size=0):
    """All entries select one physical BL block; index IDs need not be unique."""
    index = 20 + len(payload)
    header = struct.pack("<4sHBBII", b"VLT1", count, 0, 0, index, index)
    entry = struct.pack("<HBBIIHH", 1, 1, flags, 0, 16, 4 + len(payload), declared_size)
    return header + b"BL\x01\x00" + payload + entry * count


class LegacyPreflight(unittest.TestCase):
    def test_all_supplied_legacy_samples_remain_permitted(self):
        samples = {"LIBRA-98": ("s01.dat", "s02.dat", "s03.dat", "s04.dat"),
                   "LABLOG": ("s05.dat", "s06.dat", "s07.dat"),
                   "VAULT": ("s08.dat", "s09.dat", "s10.dat"),
                   "WKS": ("s11.wks", "s12.wks", "s13.wks"),
                   "CVT": ("s18.cvt", "s19.cvt"),
                   "EBCDIC-DUMP": ("s20.000", "s21.000", "s22.000")}
        for fmt, names in samples.items():
            for name in names:
                with self.subTest(format=fmt, name=name):
                    self.assertIsNone(_limits.resource_issue((SAMPLES / name).read_bytes(), fmt))

    def test_generic_legacy_input_ceiling_is_inclusive(self):
        for fmt in ("LIBRA-98", "VAULT", "CVT"):
            with patch.object(_limits, "MAX_LEGACY_INPUT_BYTES", 16):
                self.assertIsNone(_limits.resource_issue(b"\0" * 16, fmt))
                reason = _limits.resource_issue(b"\0" * 17, fmt)
            self.assertIn("legacy decoder safety limit", reason)

    def test_dense_sample_cell_and_damage_projections_are_inclusive(self):
        for fmt, minimum in (("LABLOG", 2), ("WKS", 4), ("EBCDIC-DUMP", 5)):
            with self.subTest(format=fmt), patch.object(_limits, "MAX_STRUCTURAL_ITEMS", 3):
                self.assertIsNone(_limits.resource_issue(b"\0" * (minimum * 3), fmt))
                reason = _limits.resource_issue(b"\0" * (minimum * 3 + 1), fmt)
                self.assertIn("structural-item projection", reason)

    def test_oversize_legacy_inputs_refused_without_inspecting_their_payload(self):
        class VirtualLargeInput:
            def __len__(self):
                return 100 * 1024 * 1024

            def __getitem__(self, key):
                raise AssertionError("preflight should reject before reading payload bytes")

        for fmt in _limits.LEGACY_FORMATS:
            reason = _limits.resource_issue(VirtualLargeInput(), fmt)
            self.assertIn("safety limit", reason)

    def test_other_adapters_keep_their_own_budgets(self):
        for fmt in ("PAK", "WAD", "WPD", "BRAVO", "UNKNOWN", "FUTURE"):
            with patch.object(_limits, "MAX_LEGACY_INPUT_BYTES", 2):
                self.assertIsNone(_limits.resource_issue(b"large", fmt))

    def test_vault_small_aliased_rle_input_is_refused(self):
        data = vault_aliases(100, b"A" + b"\x90\xff" * 400, flags=1)
        self.assertLess(len(data), 4096)
        reason = _limits.resource_issue(data, "VAULT")
        self.assertIn("projected payload work", reason)

    def test_vault_expansion_bound_does_not_trust_declared_decoded_size(self):
        for declared in (0, 1, 65535):
            data = vault_aliases(100, b"A" + b"\x90\xff" * 400, flags=3, declared_size=declared)
            self.assertIn("projected payload work", _limits.resource_issue(data, "VAULT"))

    def test_vault_plain_payload_aliases_are_charged_repeatedly(self):
        data = vault_aliases(30, b"A" * 4096)
        with patch.object(_limits, "MAX_VAULT_WORK_BYTES", 500_000):
            reason = _limits.resource_issue(data, "VAULT")
        self.assertIn("projected payload work", reason)

    def test_vault_fixed_record_and_name_allowance_bounds_empty_entries(self):
        data = vault_aliases(20, b"")
        with patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", 19 * _limits.VAULT_ENTRY_OUTPUT_CHARGE):
            reason = _limits.resource_issue(data, "VAULT")
        self.assertIn("projected output", reason)

    def test_vault_text_width_output_budget_is_independent_of_work_budget(self):
        data = vault_aliases(2, b"A" * 100)
        threshold = 2 * _limits.VAULT_ENTRY_OUTPUT_CHARGE + 4 * 100
        with patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", threshold):
            reason = _limits.resource_issue(data, "VAULT")
        self.assertIn("projected output", reason)

    def test_vault_only_physically_present_declared_entries_are_examined(self):
        data = bytearray(vault_aliases(1, b"A" * 10))
        struct.pack_into("<H", data, 4, 65535)
        with patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", _limits.VAULT_ENTRY_OUTPUT_CHARGE + 40):
            self.assertIsNone(_limits.resource_issue(data, "VAULT"))

    def test_vault_ignores_physical_bytes_beyond_declared_index_count(self):
        data = bytearray(vault_aliases(10, b"A" * 10))
        struct.pack_into("<H", data, 4, 1)
        with patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", _limits.VAULT_ENTRY_OUTPUT_CHARGE + 40):
            self.assertIsNone(_limits.resource_issue(data, "VAULT"))

    def test_vault_invalid_block_references_do_not_project_payload_work(self):
        for offset, stored in ((0, 65535), (0xFFFFFFFF, 65535), (16, 3), (21, 10)):
            data = bytearray(vault_aliases(1, b"A"))
            index = struct.unpack_from("<I", data, 8)[0]
            struct.pack_into("<IH", data, index + 8, offset, stored)
            with self.subTest(offset=offset, stored=stored), patch.object(_limits, "MAX_VAULT_WORK_BYTES", 0):
                self.assertIsNone(_limits.resource_issue(data, "VAULT"))

    def test_vault_invalid_or_truncated_index_stays_decoder_responsibility(self):
        for size in range(16):
            self.assertIsNone(_limits.resource_issue(b"\xff" * size, "VAULT"))
        for index in (0, 15, 0xFFFFFFFF):
            data = bytearray(vault_aliases(1, b"A"))
            struct.pack_into("<I", data, 8, index)
            self.assertIsNone(_limits.resource_issue(data, "VAULT"))

    def test_vault_zero_count_has_no_payload_projection(self):
        data = bytearray(vault_aliases(1, b"A" * 100))
        struct.pack_into("<H", data, 4, 0)
        with patch.object(_limits, "MAX_VAULT_WORK_BYTES", 0), patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", 0):
            self.assertIsNone(_limits.resource_issue(data, "VAULT"))


if __name__ == "__main__":
    unittest.main()
