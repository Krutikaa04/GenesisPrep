"""Resource and filesystem boundaries shared by all adapters."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import CAN_SYMLINK, SAMPLES, SYMLINK_SKIP_REASON, check_contract
from deadbits import engine
from deadbits.model import Result


class Platform(unittest.TestCase):
    def test_bytes_limit_is_checked_before_detection(self):
        with patch.object(engine, "MAX_INPUT_BYTES", 4), patch.object(engine, "ADAPTERS", []) as adapters:
            result = engine.salvage_bytes(b"12345", "large")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["size"], 5)
        self.assertEqual(result.damage[0]["kind"], "bad_length")

    def test_sparse_oversize_file_is_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.dat"
            with source.open("wb") as stream:
                stream.truncate(engine.MAX_INPUT_BYTES + 1)
            with patch("deadbits.engine.os.open") as open_file:
                result = engine.salvage_file(source)
            open_file.assert_not_called()
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.metadata["size"], engine.MAX_INPUT_BYTES + 1)

    def test_100_mib_input_uses_bounded_unknown_metadata(self):
        data = b"\x00" * (100 * 1024 * 1024)
        with patch.object(engine, "_entropy", wraps=engine._entropy) as entropy:
            result = engine.salvage_bytes(data, "large-unknown")
        self.assertEqual(result.status, "unrecognized")
        self.assertEqual(result.metadata["size"], len(data))
        self.assertEqual(len(entropy.call_args.args[0]), engine.ANALYSIS_BYTES)
        self.assertEqual(result.metadata["analysis_prefix_bytes"], engine.ANALYSIS_BYTES)

    def test_unknown_long_printable_runs_cannot_expand_output(self):
        result = engine.unrecognized(b"a" * (2 * engine.ANALYSIS_BYTES), "text")
        self.assertEqual(len(result.metadata["printable_strings"]), 10)
        self.assertTrue(all(len(s) <= 256 for s in result.metadata["printable_strings"]))

    def test_permission_failure_isolated(self):
        with patch("deadbits.engine.os.open", side_effect=PermissionError("denied")):
            result = engine.salvage_file(SAMPLES / "s01.dat")
        self.assertEqual(result.status, "failed")
        check_contract(self, result)
        self.assertIn("PermissionError", result.notes[0])

    def test_file_replaced_during_open_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            source, other = Path(directory) / "source", Path(directory) / "other"
            source.write_bytes(b"source")
            other.write_bytes(b"other")
            real_open = os.open
            with patch("deadbits.engine.os.open", side_effect=lambda path, flags: real_open(other, flags)):
                result = engine.salvage_file(source)
            self.assertEqual(result.status, "failed")
            self.assertIn("changed", result.notes[0])

    @unittest.skipUnless(CAN_SYMLINK, SYMLINK_SKIP_REASON)
    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "link"
            source.symlink_to(SAMPLES / "s01.dat")
            result = engine.salvage_file(source)
            self.assertEqual((result.status, result.records), ("failed", []))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_fifo_does_not_block(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pipe"
            os.mkfifo(source)
            self.assertEqual(engine.salvage_file(source).status, "failed")

    def test_damage_offsets_are_clamped_at_both_bounds(self):
        result = Result("test", "PAK", "partial")
        result.size = 4
        result.add_damage("bad_length", -5, "negative")
        result.add_damage("truncated", 100, "past end")
        self.assertEqual([d["offset"] for d in result.to_dict()["damage"]], [0, 4])

    def test_legacy_resource_refusal_preserves_identified_format(self):
        from deadbits import _large, _limits
        from deadbits.formats import lablog
        # A coarse size projection now permits a proved affordable path. Force
        # the actual physical-item budget too, preserving refusal-before-decode.
        with patch.object(_limits, "MAX_STRUCTURAL_ITEMS", 1), patch.object(_large, "MAX_ITEMS", 1), patch.object(lablog, "decode") as decode:
            result = engine.salvage_bytes((SAMPLES / "s05.dat").read_bytes(), "large-log")
        decode.assert_not_called()
        self.assertEqual((result.format, result.status), ("LABLOG", "failed"))
        self.assertEqual(result.damage[0]["kind"], "bad_length")

    def test_oversize_legacy_detection_never_receives_full_input(self):
        from deadbits.formats import lablog
        data = (SAMPLES / "s05.dat").read_bytes() + bytes(engine.MAX_LEGACY_INPUT_BYTES)
        with patch.object(lablog, "detect", wraps=lablog.detect) as detect, patch.object(lablog, "decode") as decode:
            result = engine.salvage_bytes(data, "large-log")
        self.assertEqual(len(detect.call_args.args[0]), engine.DETECTION_PREFIX_BYTES)
        decode.assert_not_called()
        self.assertEqual((result.format, result.status), ("LABLOG", "failed"))
