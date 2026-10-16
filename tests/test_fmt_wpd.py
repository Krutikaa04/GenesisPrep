"""Independent WPD framing fixtures plus official-document regressions."""
import random
import struct
import unittest
from unittest.mock import patch

from helpers import SAMPLES, check_contract, salvage_bytes
from deadbits.formats import wpd


def document(text, suffix=b"", **header):
    data = bytearray(48)
    data[:4] = wpd.MAGIC
    struct.pack_into("<I", data, 4, 48)
    data[8:12] = bytes((1, 10, 2, 0))
    struct.pack_into("<H", data, 34, 48 + len(text))
    for field, value in header.items():
        if field == "key":
            struct.pack_into("<H", data, 12, value)
        else:
            data[{"product": 8, "filetype": 9, "major": 10, "minor": 11}[field]] = value
    return bytes(data) + text + suffix


def variable(code, payload=b"", subcode=7):
    size = struct.pack("<H", len(payload) + 4)
    return bytes((code, subcode)) + size + payload + size + bytes((subcode, code))


class WPD(unittest.TestCase):
    def test_official_text_and_summary_boundary(self):
        res = salvage_bytes((SAMPLES / "s14.wpd").read_bytes(), "renamed.bin")
        self.assertEqual(res.format, "WPD")
        self.assertEqual(res.status, "ok")
        self.assertEqual([r["text"] for r in res.records], [
            "MEMORANDUM", "To: All staff", "Subject: Revised filing deadline",
            "The quarterly returns are due on the 15th. Late submissions will be returned unprocessed.",
            "Ref:\tMr. Smith, cooperation notes attached."])
        self.assertNotIn("Municipal Works", str(res.records))

    def test_official_truncation_preserves_completed_paragraphs(self):
        res = salvage_bytes((SAMPLES / "s15.wpd").read_bytes(), "renamed.bin")
        self.assertEqual(res.status, "partial")
        self.assertEqual(res.records[-1]["text"], "Please note: deadline")
        self.assertFalse(res.records[-1]["verified"])
        self.assertEqual([d["kind"] for d in res.damage], ["truncated"])
        self.assertTrue(all("verified" not in r for r in res.records[:-1]))

    def test_paragraphs_page_breaks_and_page_two(self):
        res = wpd.decode(document(b"First\n\n\x0cSecond\x0cThird\n"), "x")
        self.assertEqual(res.status, "ok")
        self.assertEqual([(r["index"], r["type"], r["text"]) for r in res.records], [
            (0, "paragraph", "First"), (1, "paragraph", ""), (2, "page_break", ""),
            (3, "paragraph", "Second"), (4, "page_break", ""), (5, "paragraph", "Third")])

    def test_spacing_and_kit_hyphen_assumptions(self):
        res = wpd.decode(document(b"a\rb\x0bc\xa0d\xa9e\xaaf\tZ\n"), "x")
        self.assertEqual(res.records[0]["text"], "a b c d-ef\tZ")
        self.assertEqual(res.status, "ok")

    def test_extended_ascii_set_zero_known_answers(self):
        # WP5 C0 layout is gate, character number, character set, gate.
        # Expected ASCII comes from the encoding definition, never decode().
        expected = bytes(range(32, 127)).decode("ascii")
        text = b"".join(bytes((0xC0, value, 0, 0xC0)) for value in range(32, 127))
        data = document(text + b"\n\x0cAfter\n")
        res = salvage_bytes(data, "extended.bin")
        check_contract(self, res, len(data))
        self.assertEqual((res.format, res.status), ("WPD", "ok"))
        self.assertEqual(res.records, [
            {"index": 0, "type": "paragraph", "text": expected},
            {"index": 1, "type": "page_break", "text": ""},
            {"index": 2, "type": "paragraph", "text": "After"}])
        self.assertEqual(res.damage, [])

    def test_extended_unsupported_sets_and_nonprintable_ascii_stay_uncertain(self):
        candidates = [(value, 0) for value in range(256) if not 32 <= value < 127]
        candidates += [(65, charset) for charset in range(1, 256)]
        for value, charset in candidates:
            with self.subTest(value=value, charset=charset):
                group = bytes((0xC0, value, charset, 0xC0))
                res = wpd.decode(document(b"Before\nA" + group + b"B\nAfter\n"), "x")
                self.assertEqual(res.records, [
                    {"index": 0, "type": "paragraph", "text": "Before"},
                    {"index": 1, "type": "paragraph", "text": "A\ufffdB",
                     "verified": False, "issues": ["unknown_record"]},
                    {"index": 2, "type": "paragraph", "text": "After"}])
                self.assertEqual(res.status, "partial")
                self.assertEqual(res.damage[0]["offset"], 56)

    def test_additional_single_byte_function_known_answers(self):
        for code in (0x8C, 0x90, 0x99):
            with self.subTest(code=hex(code)):
                res = wpd.decode(document(b"First" + bytes((code,)) + b"\x0cSecond\n"), "x")
                self.assertEqual(res.records, [
                    {"index": 0, "type": "paragraph", "text": "First"},
                    {"index": 1, "type": "page_break", "text": ""},
                    {"index": 2, "type": "paragraph", "text": "Second"}])
                self.assertEqual(res.status, "ok")
        for code, expected in ((0x93, " "), (0x94, " "), (0x95, " "), (0xAB, "-"),
                               (0xAC, "\u00ad"), (0xAD, "\u00ad"), (0xAE, "\u00ad")):
            with self.subTest(code=hex(code)):
                res = wpd.decode(document(b"A" + bytes((code,)) + b"B\n"), "x")
                self.assertEqual(res.records, [{"index": 0, "type": "paragraph", "text": "A" + expected + "B"}])
                self.assertEqual(res.status, "ok")
                self.assertEqual(res.damage, [])

    def test_page_layout_functions_have_no_text_payload(self):
        # Literal independently assembled frames, not parser widths or enums.
        frames = (
            bytes.fromhex("d0 01 0c00 0000 0000 9001 b004 0c00 01 d0"),  # left/right margins
            bytes.fromhex("d0 02 0800 0001 0002 0800 02 d0"),  # line spacing
            bytes.fromhex("d0 05 0c00 0000 0000 b004 b004 0c00 05 d0"),  # top/bottom margins
            bytes.fromhex("d0 06 0600 00 03 0600 06 d0"),  # justification
        )
        for frame in frames:
            with self.subTest(frame=frame.hex()):
                res = wpd.decode(document(b"Before\nA" + frame + b"B\n\x0cAfter\n"), "x")
                self.assertEqual(res.records, [
                    {"index": 0, "type": "paragraph", "text": "Before"},
                    {"index": 1, "type": "paragraph", "text": "AB"},
                    {"index": 2, "type": "page_break", "text": ""},
                    {"index": 3, "type": "paragraph", "text": "After"}])
                self.assertEqual(res.status, "ok")
                self.assertEqual(res.damage, [])

    def test_page_layout_unknown_lengths_and_justifications_stay_uncertain(self):
        for subcode, width in ((1, 8), (2, 4), (5, 8), (6, 2)):
            for size in (0, width - 1, width + 1):
                frame = variable(0xD0, b"X" * size, subcode)
                res = wpd.decode(document(b"A" + frame + b"B\n"), "x")
                self.assertEqual(res.status, "partial")
                self.assertEqual(res.records[0]["text"], "AB")
                self.assertEqual(res.records[0]["issues"], ["unknown_record"])
                self.assertFalse(res.records[0]["verified"])
        for payload in (b"\0\x05", b"\xff\0", b"\x01\xff"):
            res = wpd.decode(document(b"A" + variable(0xD0, payload, 6) + b"B\n"), "x")
            self.assertEqual(res.status, "partial")
            self.assertFalse(res.records[0]["verified"])
        for old in range(5):
            for new in range(5):
                res = wpd.decode(document(b"A" + variable(0xD0, bytes((old, new)), 6) + b"B\n"), "x")
                self.assertEqual(res.records, [{"index": 0, "type": "paragraph", "text": "AB"}])
                self.assertEqual(res.status, "ok")

    def test_layout_payload_controls_do_not_create_paragraphs_or_page_breaks(self):
        for subcode, payload in ((1, b"\n\x0c\xc0\x41\0\xc0\x90\x99"),
                                 (2, b"\n\x0c\x90\x99"), (5, b"FAKE\n\x0c\x90\x99")):
            res = wpd.decode(document(b"A" + variable(0xD0, payload, subcode) + b"B\n"), "x")
            self.assertEqual(res.records, [{"index": 0, "type": "paragraph", "text": "AB"}])
            self.assertEqual(res.status, "ok")

    def test_new_character_and_layout_frames_require_complete_boundaries(self):
        frames = (b"\xc0A\0\xc0", bytes.fromhex("d0 06 0600 00 03 0600 06 d0"))
        for frame in frames:
            for keep in range(1, len(frame)):
                data = document(b"Good\nPrefix" + frame[:keep], frame[keep:] + b"Not text\n")
                res = wpd.decode(data, "x")
                check_contract(self, res, len(data))
                self.assertEqual([r["text"] for r in res.records], ["Good", "Prefix"])
                self.assertEqual(res.status, "partial")
                self.assertFalse(res.records[-1]["verified"])
                self.assertEqual(res.damage[0]["kind"], "truncated")
            broken = frame[:-1] + b"!"
            res = wpd.decode(document(b"Good\nPrefix" + broken + b"LEAK\n"), "x")
            self.assertEqual([r["text"] for r in res.records], ["Good", "Prefix"])
            self.assertEqual(res.damage[0]["kind"], "bad_length")

    def test_new_functions_obey_byte_and_record_budgets(self):
        frames = (b"\xc0A\0\xc0", bytes.fromhex("d0 06 0600 00 03 0600 06 d0"))
        for frame in frames:
            for keep in range(1, len(frame)):
                with patch.object(wpd, "MAX_TEXT_BYTES", 6 + keep):
                    res = wpd.decode(document(b"Good\nA" + frame + b"B\n"), "x")
                self.assertEqual([r["text"] for r in res.records], ["Good", "A"])
                self.assertFalse(res.records[-1]["verified"])
                self.assertEqual(res.records[-1]["issues"], ["bad_length"])
                self.assertEqual(res.damage[0]["offset"], 54)
        for code in (0x8C, 0x90, 0x99):
            with patch.object(wpd, "MAX_RECORDS", 2):
                res = wpd.decode(document(b"A" + bytes((code,)) + b"B" + bytes((code,)) + b"C\n"), "x")
            self.assertEqual([r["text"] for r in res.records], ["A", "B"])
            self.assertEqual(res.status, "partial")
            self.assertEqual(res.damage[0]["kind"], "bad_length")

    def test_all_fixed_function_widths_skip_payload(self):
        widths = (4, 9, 11, 3, 3, 5, 6, 7, 4, 5, 6, 6, 8, 10, 10, 12)
        for code, width in enumerate(widths, 0xC0):
            with self.subTest(code=hex(code)):
                func = bytes((code,)) + b"X" * (width - 2) + bytes((code,))
                res = wpd.decode(document(b"A" + func + b"B\n"), "x")
                self.assertEqual(res.records[0]["text"], "A\ufffdB" if code == 0xC0 else "AB")
                self.assertEqual(res.status, "ok" if code in (0xC3, 0xC4) else "partial")
                if code not in (0xC3, 0xC4):
                    self.assertFalse(res.records[0]["verified"])
                    self.assertEqual(res.records[0]["issues"], ["unknown_record"])
                    self.assertEqual(res.damage[0]["kind"], "unknown_record")
                    self.assertTrue(res.damage[0]["lossy"])

    def test_all_variable_functions_use_mirrored_framing(self):
        for code in range(0xD0, 0x100):
            for payload in (b"", b"PRINTABLE\n\x0c\xc3\x0c\xc3", bytes(range(256))):
                with self.subTest(code=hex(code), size=len(payload)):
                    res = wpd.decode(document(b"A" + variable(code, payload) + b"B\n"), "x")
                    self.assertEqual(res.status, "partial")
                    self.assertEqual(res.records, [{"index": 0, "type": "paragraph", "text": "AB",
                                                   "verified": False, "issues": ["unknown_record"]}])
                    self.assertEqual(res.damage[0]["kind"], "unknown_record")
                    self.assertTrue(res.damage[0]["lossy"])

    def test_delimited_embedded_text_is_omitted_with_explicit_uncertainty(self):
        # Valid framing cannot prove that a footnote/header/unseen function
        # payload is merely decoration or belongs in the main paragraph.
        for code in (0xD5, 0xD6, 0xF0, 0xFE):
            res = wpd.decode(document(b"Before\nA" + variable(code, b"Embedded text\n") + b"B\nAfter\n"), "x")
            self.assertEqual([r["text"] for r in res.records], ["Before", "AB", "After"])
            self.assertFalse(res.records[1]["verified"])
            self.assertEqual(res.records[1]["issues"], ["unknown_record"])
            self.assertTrue(all("verified" not in r for r in (res.records[0], res.records[2])))
            self.assertEqual(res.status, "partial")
            self.assertTrue(res.damage[0]["lossy"])
        res = wpd.decode(document(b"Before\n" + variable(0xD6, b"Embedded only\n")), "x")
        self.assertEqual([r["text"] for r in res.records], ["Before"])
        self.assertEqual(res.status, "partial")
        self.assertEqual(res.damage[0]["kind"], "unknown_record")

    def test_variable_suffix_corruption_never_leaks_payload(self):
        original = variable(0xF1, b"FAKE\nVERIFIED\n")
        for offset in (-4, -3, -2, -1):
            data = bytearray(original)
            data[offset] ^= 1
            res = wpd.decode(document(b"Intact\nPrefix" + data + b"Later\n"), "x")
            self.assertEqual(res.records[0]["text"], "Intact")
            self.assertEqual(res.records[1]["text"], "Prefix")
            self.assertFalse(res.records[1]["verified"])
            self.assertEqual(res.records[1]["issues"], ["bad_length"])
            self.assertNotIn("FAKE", str(res.records))
            self.assertEqual(res.status, "partial")

    def test_fixed_bad_gate_never_leaks_payload(self):
        res = wpd.decode(document(b"Good\nPrefix\xc1FAKE\nZ\n!Later\n"), "x")
        self.assertEqual([r["text"] for r in res.records], ["Good", "Prefix"])
        self.assertFalse(res.records[-1]["verified"])
        self.assertEqual(res.damage[0]["kind"], "bad_length")

    def test_oversized_small_and_truncated_functions(self):
        for code in (0xD0, 0xEF, 0xF0, 0xFF):
            for raw in (bytes((code,)), bytes((code, 7, 255, 255)), bytes((code, 7, 0, 0))):
                with self.subTest(raw=raw):
                    res = wpd.decode(document(b"Good\nPrefix" + raw), "x")
                    self.assertEqual([r["text"] for r in res.records], ["Good", "Prefix"])
                    self.assertFalse(res.records[-1]["verified"])
                    self.assertEqual(res.status, "partial")
        for code in (0xC0, 0xC3, 0xCF):
            res = wpd.decode(document(b"Good\n" + bytes((code,))), "x")
            self.assertEqual(len(res.records), 1)
            self.assertEqual(res.damage[0]["kind"], "truncated")

    def test_function_header_cannot_read_into_summary(self):
        data = document(b"Good\nPrefix\xf0\x07", b"\x00\x00SUMMARY")
        res = wpd.decode(data, "x")
        self.assertEqual([r["text"] for r in res.records], ["Good", "Prefix"])
        self.assertEqual(res.damage[0]["kind"], "truncated")
        self.assertFalse(res.records[-1]["verified"])

    def test_short_legacy_length_guess_is_rejected(self):
        # Former +5 guess had no corroborating trailing size/subcode.
        guessed = b"\xf0\x07\x04\x00FAKE\xf0"
        res = wpd.decode(document(b"Good\n" + guessed + b"Later\n"), "x")
        self.assertEqual([r["text"] for r in res.records], ["Good"])
        self.assertEqual(res.status, "partial")

    def test_encrypted_is_unsupported_without_text(self):
        for key in (1, 256, 65535):
            data = document(b"Secret\n", key=key)
            for candidate in (data, data[:14]):
                res = salvage_bytes(candidate, "x")
                self.assertEqual(res.format, "WPD")
                self.assertEqual(res.status, "unsupported")
                self.assertEqual(res.records, [])
                self.assertEqual([d["kind"] for d in res.damage], ["encrypted"])

    def test_other_products_types_and_versions_are_explicitly_unsupported(self):
        for kwargs in ({"product": 2}, {"filetype": 1}, {"filetype": 13}, {"major": 0},
                       {"major": 255}, {"minor": 1}):
            data = document(b"Not established\n", **kwargs)
            res = salvage_bytes(data, "x")
            self.assertEqual(res.format, "WPD", kwargs)
            self.assertEqual(res.status, "unsupported", kwargs)
            self.assertEqual(res.records, [], kwargs)
            self.assertEqual(res.damage[0]["kind"], "unknown_record")

    def test_bad_document_and_text_end_pointers(self):
        for offset, fmt, value in ((4, "<I", 0), (4, "<I", 0xFFFFFFFF), (34, "<H", 47)):
            data = bytearray(document(b"Text\n", b"Summary"))
            struct.pack_into(fmt, data, offset, value)
            res = wpd.decode(bytes(data), "x")
            self.assertEqual(res.status, "failed")
            self.assertEqual(res.records, [])
            self.assertEqual(res.damage[0]["kind"], "oob_pointer")

    def test_unknown_text_byte_marks_only_affected_paragraph(self):
        for value in (0, 1, 0x7F, 0x80, 0xBF):
            res = wpd.decode(document(b"Before\nA" + bytes((value,)) + b"B\nAfter\n"), "x")
            self.assertEqual(res.records[1]["text"], "A\ufffdB")
            self.assertFalse(res.records[1]["verified"])
            self.assertEqual(res.records[1]["issues"], ["invalid_value"])
            self.assertTrue(all("verified" not in r for r in (res.records[0], res.records[2])))

    def test_detection_requires_more_than_magic(self):
        for data in (b"", wpd.MAGIC, wpd.MAGIC + b"\x00" * 9, wpd.MAGIC + b"\x00" * 60):
            self.assertEqual(wpd.detect(data), 0)
        self.assertGreater(wpd.detect(document(b"Text\n")), 0)

    def test_record_budget_preserves_prior_records_and_reports_loss(self):
        with patch.object(wpd, "MAX_RECORDS", 2):
            res = wpd.decode(document(b"A\nB\nC\n"), "x")
        self.assertEqual([r["text"] for r in res.records], ["A", "B"])
        self.assertEqual(res.status, "partial")
        self.assertEqual([d["kind"] for d in res.damage], ["bad_length"])
        self.assertTrue(res.damage[0]["lossy"])
        self.assertTrue(all("verified" not in r for r in res.records))
        with patch.object(wpd, "MAX_RECORDS", 1):
            res = wpd.decode(document(b"A\x0cB\n"), "x")
        self.assertEqual([r["text"] for r in res.records], ["A"])
        self.assertEqual(res.status, "partial")

    def test_text_budget_bounds_consumed_characters_and_partial_prefix(self):
        with patch.object(wpd, "MAX_TEXT_BYTES", 7):
            res = wpd.decode(document(b"A\nBCDEFG\nZ\n"), "x")
        self.assertEqual([r["text"] for r in res.records], ["A", "BCDEF"])
        self.assertFalse(res.records[-1]["verified"])
        self.assertEqual(res.records[-1]["issues"], ["bad_length"])
        self.assertEqual(res.damage[0]["offset"], 55)
        self.assertEqual(res.status, "partial")
        with patch.object(wpd, "MAX_TEXT_BYTES", 2), patch.object(wpd, "MAX_RECORDS", 1):
            exact = wpd.decode(document(b"A\n"), "x")
        self.assertEqual(exact.status, "ok")
        self.assertEqual(exact.damage, [])

    def test_function_payload_skipping_obeys_byte_budget_without_scanning_it(self):
        data = document(b"Good\n" + variable(0xF0, b"X" * 32_000) + b"After\n")
        with patch.object(wpd, "MAX_TEXT_BYTES", 10), patch.object(wpd, "_fn_len", wraps=wpd._fn_len) as lengths:
            res = wpd.decode(data, "x")
        self.assertEqual(lengths.call_count, 1)
        self.assertEqual([r["text"] for r in res.records], ["Good"])
        self.assertEqual(res.status, "partial")
        self.assertEqual(res.damage[0]["kind"], "bad_length")
        with patch.object(wpd, "MAX_TEXT_BYTES", 3), patch.object(wpd, "_fn_len", wraps=wpd._fn_len) as lengths:
            res = wpd.decode(document(b"A" + variable(0xF0, b"X" * 32_000)), "x")
        self.assertEqual(lengths.call_count, 0)
        self.assertEqual(res.records[0]["text"], "A")
        self.assertFalse(res.records[0]["verified"])

    def test_direct_decoder_never_raises_for_truncation_and_seeded_junk(self):
        source = (SAMPLES / "s14.wpd").read_bytes()
        rng = random.Random(303)
        candidates = [source[:i] for i in range(len(source))]
        candidates += [bytes(rng.randrange(256) for _ in range(rng.randrange(400))) for _ in range(200)]
        for data in candidates:
            check_contract(self, wpd.decode(data, "x"), len(data))
