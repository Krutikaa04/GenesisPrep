"""WKS damage matrix and number-format / date tests (M2-3, M2-4)."""
import struct
import unittest

from helpers import SAMPLES, check_contract, salvage_bytes


def rec(op, payload=b""):
    return struct.pack("<HH", op, len(payload)) + payload


BOF = rec(0, struct.pack("<H", 0x0404))
EOF_ = rec(1)


def label(col, row, text, fmt=0xFF, prefix="'"):
    return rec(0x0F, struct.pack("<BHH", fmt, col, row) + (prefix + text).encode("latin-1") + b"\0")


def integer(col, row, v, fmt=0xFF):
    return rec(0x0D, struct.pack("<BHHh", fmt, col, row, v))


def number(col, row, v, fmt=0xFF):
    return rec(0x0E, struct.pack("<BHHd", fmt, col, row, v))


def blank(col, row, fmt=0xFF):
    return rec(0x0C, struct.pack("<BHH", fmt, col, row))


def formula(col, row, cached, tokens=b"\x00\x01", fmt=0xFF):
    return rec(0x10, struct.pack("<BHHdH", fmt, col, row, cached, len(tokens)) + tokens)


def sheet(*records, head=True, eof=True):
    settings = rec(0x06, struct.pack("<4H", 0, 0, 3, 5)) + rec(2, b"\xFF") + rec(3, b"\x00") + rec(4, b"\x00") \
        + rec(5, b"\x00") + rec(7, bytes(31)) + rec(8, struct.pack("<HB", 0, 12))
    return (BOF + settings if head else b"") + b"".join(records) + (EOF_ if eof else b"")


CELLS = (label(0, 0, "Item"), integer(0, 1, 7), number(1, 1, 2.5), formula(2, 1, 9.5), blank(3, 1))


class Base(unittest.TestCase):
    def run_(self, data, name="t.wks"):
        res = salvage_bytes(data, name)
        check_contract(self, res, len(data), name)
        return res

    def kinds(self, res):
        return [d["kind"] for d in res.damage]

    def cell(self, res, ref):
        return [r for r in res.records if r["cell"] == ref][0]


class WksBuilt(Base):
    def test_clean(self):
        res = self.run_(sheet(*CELLS))
        self.assertEqual((res.format, res.status, res.damage), ("WKS", "ok", []))
        self.assertEqual([r["cell"] for r in res.records], ["A1", "A2", "B2", "C2", "D2"])
        self.assertEqual(self.cell(res, "A1")["alignment"], "left")
        self.assertEqual(self.cell(res, "C2")["cached_value"], 9.5)
        self.assertEqual(self.cell(res, "C2")["formula_raw_hex"], "0001")
        self.assertEqual(res.metadata["version_code"], "0x0404")
        self.assertEqual(res.metadata["declared_range"], "A1:D6")
        self.assertEqual(res.metadata["column_widths"], {"A": 12})

    def test_label_alignment_prefixes(self):
        res = self.run_(sheet(*[label(i, 0, "x", prefix=p) for i, p in enumerate("'\"^\\")]))
        self.assertEqual([r["alignment"] for r in res.records], ["left", "right", "center", "repeat"])

    # --- number formats (one test per family) -------------------------------------------------------
    def test_number_format_families_emit_no_key_like_the_s11_reference(self):
        for name, fmt in (("fixed", 0x02), ("scientific", 0x12), ("currency", 0x22), ("percent", 0x32),
                          ("comma", 0x42)):
            res = self.run_(sheet(number(0, 0, 1234.5, fmt)))
            self.assertNotIn("number_format", res.records[0], name)

    def test_date_and_time_formats(self):
        for d, want in ((1, "date:D1"), (2, "date:D2"), (3, "date:D3"), (4, "date:D4"), (5, "date:D5"),
                        (6, "time:T1"), (7, "time:T2"), (8, "time:T3"), (9, "time:T4")):
            res = self.run_(sheet(number(0, 0, 36526, 0x70 | d)))
            self.assertEqual(res.records[0]["number_format"], want)

    def test_unknown_special_format_is_reported_not_guessed(self):
        res = self.run_(sheet(number(0, 0, 1, 0x7F)))
        self.assertEqual(res.records[0]["number_format"], "special:15")

    # --- date serials ------------------------------------------------------------------------------
    def iso(self, serial, kind="number"):
        cell = number(0, 0, serial, 0x71) if kind == "number" else integer(0, 0, serial, 0x71)
        return self.run_(sheet(cell)).records[0].get("iso_date")

    def test_iso_date_serials(self):
        self.assertEqual(self.iso(1), "1900-01-01")
        self.assertEqual(self.iso(59), "1900-02-28")
        self.assertEqual(self.iso(61), "1900-03-01")          # day after the phantom 1900-02-29
        self.assertEqual(self.iso(36526), "2000-01-01")
        self.assertEqual(self.iso(73050), "2099-12-31")

    def test_serial_60_is_the_nonexistent_leap_day_so_no_iso_date(self):
        self.assertIsNone(self.iso(60))

    def test_serials_above_2_pow_15_need_a_float_cell(self):
        self.assertEqual(self.iso(40000.0), "2009-07-06")
        self.assertIsNone(self.iso(-25536, "integer"))      # an i16 cannot hold them: never wrapped into a date

    def test_fractional_serial_keeps_date_part(self):
        self.assertEqual(self.iso(36526.75), "2000-01-01")

    def test_unrepresentable_serials_do_not_crash(self):
        for v in (0, -5, 1e300, float("inf"), float("nan"), 10 ** 8):
            self.assertIsNone(self.iso(float(v)))

    def test_formula_cached_date(self):
        res = self.run_(sheet(formula(0, 0, 36526.0, fmt=0x71)))
        self.assertEqual(res.records[0]["iso_date"], "2000-01-01")

    def test_non_finite_numbers_become_null_and_unverified(self):
        res = self.run_(sheet(number(0, 0, float("nan")), number(1, 0, float("inf"))))
        for r in res.records:
            self.assertIsNone(r["value"])
            self.assertFalse(r["verified"])
        self.assertEqual(res.status, "partial")

    # --- structure damage ---------------------------------------------------------------------------
    def test_truncated_mid_record_and_mid_header(self):
        full = sheet(*CELLS)
        cut_mid_payload = full.index(number(1, 1, 2.5)) + 8
        res = self.run_(full[:cut_mid_payload])
        self.assertEqual(self.kinds(res), ["truncated"])
        self.assertEqual([r["cell"] for r in res.records], ["A1", "A2"])
        res = self.run_(full[:full.index(number(1, 1, 2.5)) + 2])
        self.assertEqual(self.kinds(res), ["truncated"])

    def test_missing_eof(self):
        res = self.run_(sheet(*CELLS, eof=False))
        self.assertEqual(self.kinds(res), ["truncated"])
        self.assertEqual(len(res.records), 5)
        self.assertEqual(res.status, "partial")

    def test_bytes_after_eof_are_reported_lossless(self):
        res = self.run_(sheet(*CELLS) + b"\xDE\xAD\xBE\xEF\x00")
        self.assertEqual(self.kinds(res), ["unparsed_bytes"])
        self.assertFalse(res.damage[0]["lossy"])
        self.assertEqual(len(res.records), 5)

    def test_missing_bof_is_unrecognized(self):
        """The 00 00 02 00 BOF header is the detection signature, so a stream without it never reaches the decoder."""
        res = self.run_(sheet(*CELLS, head=False))
        self.assertEqual((res.format, res.status), ("UNKNOWN", "unrecognized"))

    def test_unknown_version_code_is_reported_verbatim(self):
        data = b"\x00\x00\x02\x00\xff\xff" + b"".join(CELLS) + EOF_
        res = self.run_(data)
        self.assertEqual(res.metadata["version_code"], "0xffff")
        self.assertEqual(res.status, "ok")

    def test_empty_worksheet(self):
        res = self.run_(sheet())
        self.assertEqual((res.status, res.records, res.damage), ("ok", [], []))

    def test_label_without_nul_is_dropped_and_reported(self):
        bad = rec(0x0F, struct.pack("<BHH", 0xFF, 5, 5) + b"'no terminator")
        res = self.run_(sheet(label(0, 0, "ok"), bad, label(1, 0, "after")))
        self.assertEqual([r["cell"] for r in res.records], ["A1", "B1"])
        self.assertIn("bad_length", self.kinds(res))
        self.assertEqual(res.status, "partial")

    def test_cell_position_out_of_range(self):
        res = self.run_(sheet(label(0, 0, "ok"), integer(300, 0, 1), integer(0, 9000, 1)))
        self.assertEqual([r["cell"] for r in res.records], ["A1"])
        self.assertEqual(self.kinds(res), ["invalid_value", "invalid_value"])

    def test_cells_outside_declared_range_are_kept_without_damage(self):
        res = self.run_(sheet(label(40, 100, "far")))
        self.assertEqual((res.status, res.damage), ("ok", []))
        self.assertEqual(res.records[0]["cell"], "AO101")

    def test_unknown_opcode_is_skipped_lossless(self):
        res = self.run_(sheet(label(0, 0, "a"), rec(0xFA, b"\x01\x02"), label(1, 0, "b")))
        self.assertEqual([r["cell"] for r in res.records], ["A1", "B1"])
        self.assertEqual(self.kinds(res), ["unknown_record"])
        self.assertFalse(res.damage[0]["lossy"])

    def test_cell_written_twice_keeps_last_value(self):
        res = self.run_(sheet(integer(1, 3, 111), integer(1, 3, 222)))
        self.assertEqual([(r["cell"], r["value"]) for r in res.records], [("B4", 222)])

    # --- corrupted length fields (the stream has no resync marker) --------------------------------
    def test_corrupted_length_of_settings_record_does_not_swallow_cells(self):
        data = sheet(*CELLS)
        pos = data.index(rec(3, b"\x00"))
        bad = data[:pos + 2] + struct.pack("<H", 0x0101) + data[pos + 4:]
        res = self.run_(bad)
        self.assertEqual(len(res.records), 5)
        self.assertEqual(self.kinds(res), ["bad_length"])
        self.assertFalse(res.damage[0]["lossy"])
        self.assertEqual(res.status, "partial")

    def test_corrupted_length_of_integer_cell_restores_cell_unverified(self):
        data = sheet(*CELLS)
        pos = data.index(integer(0, 1, 7))
        res = self.run_(data[:pos + 2] + struct.pack("<H", 9) + data[pos + 4:])
        self.assertEqual(len(res.records), 5)
        a2 = self.cell(res, "A2")
        self.assertEqual(a2["value"], 7)
        self.assertFalse(a2["verified"])
        self.assertIn("bad_length", a2["issues"])

    def test_corrupted_length_of_label_resynchronises_and_reports_loss(self):
        data = sheet(label(0, 0, "keep1"), label(0, 1, "victim"), label(0, 2, "keep2"), label(0, 3, "keep3"),
                     label(0, 4, "keep4"))
        pos = data.index(label(0, 1, "victim"))
        res = self.run_(data[:pos + 2] + struct.pack("<H", 4) + data[pos + 4:])
        cells = [r["cell"] for r in res.records]
        self.assertIn("A1", cells)
        self.assertTrue({"A3", "A4", "A5"} <= set(cells), cells)
        self.assertNotIn("A2", cells)
        self.assertIn("unparsed_bytes", self.kinds(res))
        self.assertTrue(all(d["lossy"] for d in res.damage if d["kind"] == "unparsed_bytes"))

    def test_no_silent_loss_when_a_cell_length_is_inflated(self):
        data = sheet(*CELLS)
        pos = data.index(number(1, 1, 2.5))
        res = self.run_(data[:pos + 2] + struct.pack("<H", 60) + data[pos + 4:])
        self.assertNotEqual(res.status, "ok")

    def test_length_pointing_past_eof_is_truncated_not_ok(self):
        data = sheet(*CELLS)
        pos = data.index(integer(0, 1, 7))
        res = self.run_(data[:pos + 2] + struct.pack("<H", 0xFFF0) + data[pos + 4:])
        self.assertNotEqual(res.status, "ok")


class WksSamples(Base):
    def files(self):
        return [SAMPLES / n for n in ("s11.wks", "s12.wks", "s13.wks")]

    def test_every_truncation_is_contract_valid(self):
        for p in self.files():
            raw = p.read_bytes()
            for n in range(len(raw)):
                self.run_(raw[:n], p.name)

    def test_truncation_never_yields_a_false_verified_cell(self):
        """s12 is excluded: it deliberately writes B4 twice, so cutting before the second write leaves the
        stale first value (organizer question Q5)."""
        for p in (SAMPLES / "s11.wks", SAMPLES / "s13.wks"):
            raw = p.read_bytes()
            clean = {r["cell"]: r for r in salvage_bytes(raw, p.name).records}
            for n in range(len(raw)):
                for r in self.run_(raw[:n], p.name).records:
                    if r.get("verified", True):
                        self.assertEqual(r, clean[r["cell"]], "%s truncated to %d" % (p.name, n))

    def test_corrupting_any_record_length_field_is_never_silent(self):
        """Every opcode/length header byte of s11 flipped: if the result differs from the clean decode it must
        not claim status ok."""
        raw = (SAMPLES / "s11.wks").read_bytes()
        clean = salvage_bytes(raw, "s11.wks").records
        headers, pos = [], 0
        while pos + 4 <= len(raw):
            ln = struct.unpack_from("<H", raw, pos + 2)[0]
            headers += [pos + 2, pos + 3]
            pos += 4 + ln
        for off in headers:
            for v in (0, 1, 0xFF, raw[off] ^ 0x80):
                b = bytearray(raw)
                b[off] = v
                res = self.run_(bytes(b), "s11.wks")
                if v != raw[off] and res.records != clean:
                    self.assertNotEqual(res.status, "ok", "offset %d value %d" % (off, v))

    def test_kit_files(self):
        want = {"s11.wks": "ok", "s12.wks": "partial", "s13.wks": "partial"}
        for p in self.files():
            self.assertEqual(self.run_(p.read_bytes(), p.name).status, want[p.name], p.name)


if __name__ == "__main__":
    unittest.main()
