"""Bravo evidence/negative controls without guessing the formatting trailer."""
import random
import unittest
from unittest.mock import patch

from helpers import SAMPLES, check_contract, salvage_bytes
from deadbits.formats import bravo


TRAILER = b"\x00\x00\x06\x00\x04\x00\x0a\x02\x00\x00\x43\x00\x0f\x06\x00"


def document(text):
    return text + b"\x1a" + TRAILER


class Bravo(unittest.TestCase):
    def test_both_official_files_and_empty_paragraphs(self):
        expected = {
            "s16.bravo": ["To: Alto users", "From: Documentation", "", "The new editor supports looks. Bold and italic runs are stored after the text.", "End of memo."],
            "s17.bravo": ["Subject: Ethernet test", "Throughput reached 2.9 Mbps on the long segment.", "", "Collisions stayed below one percent.", "Signed, the lab."]}
        for filename, paragraphs in expected.items():
            data = (SAMPLES / filename).read_bytes()
            res = salvage_bytes(data, "arbitrary.bin")
            self.assertEqual(res.format, "BRAVO")
            self.assertEqual(res.status, "ok")
            self.assertEqual(res.records, [{"index": i, "text": p} for i, p in enumerate(paragraphs)])
            self.assertNotIn("format_runs", res.metadata)

    def test_plain_dos_text_with_eof_is_not_bravo(self):
        for text in (b"Plain text\r\x1a", b"Plain text\r\x1aTEXT", b"Plain text\r\x1a\r\n",
                     b"Plain text\r\x1a" + b"\x00" * 15, b"Plain text\r\x1a\x00\x01TEXT",
                     b"Not terminated\x1a" + TRAILER, b"Short\r\x1a" + TRAILER,
                     b"Plain text\r\x1a" + TRAILER + b"\x1a"):
            self.assertEqual(bravo.detect(text), 0, text)
            self.assertEqual(salvage_bytes(text, "x").status, "unrecognized", text)

    def test_short_and_missing_marker_files_are_not_identified(self):
        for length in range(8):
            self.assertEqual(bravo.detect(b"A" * length), 0)
        self.assertEqual(bravo.detect(b"Long plain text\rWith paragraphs\r"), 0)
        self.assertEqual(bravo.detect(document(b"Text\r")[:-1] + b"X" * 513), 0)

    def test_leading_consecutive_and_final_empty_paragraphs(self):
        res = bravo.decode(document(b"\rFirst\r\r\r"), "x")
        self.assertEqual([r["text"] for r in res.records], ["", "First", "", ""])
        self.assertEqual(res.status, "ok")

    def test_missing_marker_direct_decode_salvages_complete_paragraphs(self):
        data = b"First\rSecond\rFinal"
        res = bravo.decode(data, "x")
        self.assertEqual(res.status, "partial")
        self.assertEqual([r["text"] for r in res.records], ["First", "Second", "Final"])
        self.assertFalse(res.records[-1]["verified"])
        self.assertEqual([d["kind"] for d in res.damage], ["truncated"])
        self.assertTrue(all("verified" not in r for r in res.records[:-1]))

    def test_unterminated_last_paragraph_is_unverified(self):
        res = bravo.decode(document(b"First\rUnterminated"), "x")
        self.assertFalse(res.records[-1]["verified"])
        self.assertEqual(res.status, "partial")
        self.assertEqual(res.damage[0]["kind"], "invalid_value")
        self.assertTrue(res.damage[0]["lossy"])

    def test_high_bytes_and_controls_are_never_guessed_as_latin1(self):
        for value in tuple(range(0x80, 0x100)) + (0, 1, 0x7F):
            data = document(b"Before\rA" + bytes((value,)) + b"B\rAfter\r")
            self.assertEqual(bravo.detect(data), 0)
            res = bravo.decode(data, "x")
            self.assertEqual(res.records[1]["text"], "A\ufffdB")
            self.assertFalse(res.records[1]["verified"])
            self.assertEqual(res.records[1]["issues"], ["invalid_value"])
            self.assertTrue(all("verified" not in r for r in (res.records[0], res.records[2])))
            self.assertEqual(res.damage[0]["offset"], 8)

    def test_tabs_and_linefeeds_are_preserved_inside_cr_paragraphs(self):
        res = bravo.decode(document(b"First\tline\ncontinued\r"), "x")
        self.assertEqual(res.records[0]["text"], "First\tline\ncontinued")
        self.assertEqual(res.status, "ok")

    def test_unknown_trailer_does_not_invent_format_runs_or_damage(self):
        for suffix in (b"", b"ASCII", bytes(range(256))):
            res = bravo.decode(b"First\rSecond\r\x1a" + suffix, "x")
            self.assertEqual(res.metadata, {})
            self.assertEqual(res.damage, [])
            self.assertEqual([r["text"] for r in res.records], ["First", "Second"])

    def test_record_budget_preserves_prior_paragraphs_and_reports_loss(self):
        with patch.object(bravo, "MAX_RECORDS", 2):
            res = bravo.decode(document(b"A\rB\rC\r"), "x")
        self.assertEqual([r["text"] for r in res.records], ["A", "B"])
        self.assertEqual(res.status, "partial")
        self.assertEqual([d["kind"] for d in res.damage], ["bad_length"])
        self.assertTrue(res.damage[0]["lossy"])
        self.assertTrue(all("verified" not in r for r in res.records))

    def test_text_budget_bounds_consumed_characters_and_reports_prefix_uncertainty(self):
        with patch.object(bravo, "MAX_TEXT_BYTES", 7):
            res = bravo.decode(document(b"A\rBCDEFG\rZ\r"), "x")
        self.assertEqual([r["text"] for r in res.records], ["A", "BCDEF"])
        self.assertFalse(res.records[-1]["verified"])
        self.assertEqual(res.records[-1]["issues"], ["bad_length"])
        self.assertEqual(res.status, "partial")
        self.assertEqual([d["kind"] for d in res.damage], ["bad_length"])
        self.assertEqual(res.damage[0]["offset"], 7)
        with patch.object(bravo, "MAX_TEXT_BYTES", 2), patch.object(bravo, "MAX_RECORDS", 1):
            exact = bravo.decode(document(b"A\r"), "x")
        self.assertEqual(exact.status, "ok")
        self.assertEqual(exact.damage, [])

    def test_detection_window_is_bounded_before_scanning_prefix(self):
        class ObservedBytes(bytes):
            def find(self, sub, start=0, end=None):
                self.searches.append((start, end))
                return super().find(sub, start, len(self) if end is None else end)
        data = ObservedBytes(document(b"X" * 10_000 + b"\r"))
        data.searches = []
        with patch.object(bravo, "MAX_TEXT_BYTES", 32), patch.object(bravo, "_PREFIX") as prefix:
            self.assertEqual(bravo.detect(data), 0)
        self.assertEqual(data.searches, [(0, 33)])
        prefix.fullmatch.assert_not_called()
        with patch.object(bravo, "MAX_TEXT_BYTES", 32), patch.object(bravo, "MAX_RECORDS", 3):
            dense = bravo.decode(b"\r" * 10_000, "x")
        self.assertEqual(len(dense.records), 3)
        self.assertEqual(dense.status, "partial")
        self.assertEqual(dense.damage[0]["kind"], "bad_length")

    def test_direct_decoder_never_raises_on_truncated_sample_or_seeded_junk(self):
        data = (SAMPLES / "s16.bravo").read_bytes()
        rng = random.Random(333)
        candidates = [data[:i] for i in range(len(data))]
        candidates += [bytes(rng.randrange(256) for _ in range(rng.randrange(400))) for _ in range(200)]
        for candidate in candidates:
            check_contract(self, bravo.decode(candidate, "x"), len(candidate))
