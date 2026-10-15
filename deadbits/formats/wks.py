"""WKS: Lotus 1-2-3 worksheet saved on a DOS PC (early 1990s).

Record stream (little-endian): opcode u16 | length u16 | payload.  Layout confirmed on s11 (expected
output) and s12/s13 (structure only):

  0x0000 BOF  version u16 (0x0404)           0x0001 EOF
  0x0006 RANGE c0 r0 c1 r1 (4 x u16)         0x0008 COLW  col u16, width u8
  0x0002-0x0005, 0x0007, 0x000B  settings / window / named range (known, not decoded)
  0x000C BLANK   fmt u8, col u16, row u16
  0x000D INTEGER fmt, col, row, i16          0x000E NUMBER fmt, col, row, f64
  0x000F LABEL   fmt, col, row, text\0 (first char = alignment prefix ' " ^ \\ )
  0x0010 FORMULA fmt, col, row, f64 cached value, u16 token length, tokens
  fmt: 0xFF = default; high nibble 0 fixed, 1 scientific, 2 currency, 3 percent, 4 comma, 7 special
       (0x71-0x75 date formats); low nibble = decimals.
Any other opcode is skipped by its length and reported as `unknown_record`.
A cell written more than once keeps its LAST value (assumption; documented in FORMAT-SPEC).
"""
import datetime
import struct

from ..model import Result

NAME = "WKS"
KNOWN_META = {0x02, 0x03, 0x04, 0x05, 0x07, 0x0B}
MAX_COL, MAX_ROW = 255, 8191
ALIGN = {"'": "left", '"': "right", "^": "center", "\\": "repeat"}
FMT_TYPES = {0: "fixed", 1: "scientific", 2: "currency", 3: "percent", 4: "comma"}
FIXED_LEN = {0x0C: 5, 0x0D: 7, 0x0E: 13}


def col_letters(c: int) -> str:
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def detect(data: bytes) -> float:
    if data[:4] != b"\x00\x00\x02\x00":
        return 0.0
    if len(data) >= 6 and struct.unpack_from("<H", data, 4)[0] in (0x0404, 0x0406, 0x0802, 0x1000):
        return 1.0
    return 0.8


def _number_format(fmt: int):
    if fmt == 0xFF:
        return None
    t, d = fmt >> 4, fmt & 0xF
    if t != 7:
        return None   # s11 reference carries no number_format for currency cells; only date/time formats are emitted
    if t == 7:
        return {1: "date:D1", 2: "date:D2", 3: "date:D3", 4: "date:D4", 5: "date:D5",
                6: "time:T1", 7: "time:T2", 8: "time:T3", 9: "time:T4"}.get(d, "special:%d" % d)
    return "%s:%d" % (FMT_TYPES.get(t, "format%d" % t), d)


def _iso_date(serial):
    """Lotus serial -> ISO date (1900 leap-year bug: serial 60 is the non-existent 1900-02-29)."""
    try:
        n = int(serial)
        if n < 1:
            return None
        base = datetime.date(1899, 12, 31) if n < 60 else datetime.date(1899, 12, 30)
        return (base + datetime.timedelta(days=n)).isoformat() if n != 60 else None
    except (OverflowError, ValueError, TypeError):
        return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    pos, idx, eof, unverified_any = 0, 0, False, False
    cells = {}          # (row, col) -> record, keeps last write; order of first appearance preserved separately
    order = []
    widths = {}
    lossy_skipped = False

    while pos < size:
        if pos + 4 > size:
            res.add_damage("truncated", pos, "file ends inside a record header (%d bytes left)" % (size - pos), True)
            break
        op, ln = struct.unpack_from("<HH", data, pos)
        end = pos + 4 + ln
        if end > size:
            res.add_damage("truncated", pos, "record 0x%04x declares %d bytes but only %d remain" %
                           (op, ln, size - pos - 4), True)
            break
        pl = data[pos + 4:end]
        if idx == 0 and op != 0x0000:
            res.add_damage("invalid_value", pos, "first record is 0x%04x, expected BOF" % op, False)
        if op == 0x0000:
            if ln == 2:
                res.metadata["version_code"] = "0x%04x" % struct.unpack("<H", pl)[0]
            else:
                res.add_damage("bad_length", pos, "BOF length %d, expected 2" % ln, False)
        elif op == 0x0001:
            eof = True
            pos = end
            idx += 1
            break
        elif op == 0x0006:
            if ln == 8:
                c0, r0, c1, r1 = struct.unpack("<4H", pl)
                res.metadata["declared_range"] = "%s%d:%s%d" % (col_letters(c0), r0 + 1, col_letters(c1), r1 + 1)
            else:
                res.add_damage("bad_length", pos, "RANGE length %d, expected 8" % ln, False)
        elif op == 0x0008:
            if ln == 3:
                c, w = struct.unpack("<HB", pl)
                widths[col_letters(c)] = w
            else:
                res.add_damage("bad_length", pos, "COLW length %d, expected 3" % ln, False)
        elif op in KNOWN_META:
            pass
        elif op in (0x0C, 0x0D, 0x0E, 0x0F, 0x10):
            if op in FIXED_LEN and ln != FIXED_LEN[op]:
                res.add_damage("bad_length", pos, "record 0x%04x has length %d, expected %d" % (op, ln, FIXED_LEN[op]), True)
            elif op == 0x0F and ln < 6 or op == 0x10 and ln < 15:
                res.add_damage("bad_length", pos, "record 0x%04x too short (%d bytes)" % (op, ln), True)
            else:
                fmt, col, row = struct.unpack_from("<BHH", pl, 0)
                if col > MAX_COL or row > MAX_ROW:
                    res.add_damage("invalid_value", pos, "cell position col %d row %d outside worksheet" % (col, row), True)
                else:
                    rec = {"cell": "%s%d" % (col_letters(col), row + 1), "col": col, "row": row}
                    nf = _number_format(fmt)
                    ok = True
                    if op == 0x0C:
                        rec["type"] = "blank"
                    elif op == 0x0D:
                        rec["type"] = "integer"
                        rec["value"] = struct.unpack_from("<h", pl, 5)[0]
                    elif op == 0x0E:
                        rec["type"] = "number"
                        rec["value"] = struct.unpack_from("<d", pl, 5)[0]
                    elif op == 0x0F:
                        body = pl[5:]
                        if body[-1:] != b"\x00" or b"\x00" in body[:-1]:
                            res.add_damage("bad_length", pos, "label is not a single NUL-terminated string", True)
                            ok = False
                        else:
                            text = body[:-1].decode("latin-1")
                            rec["type"] = "label"
                            if text[:1] in ALIGN:
                                rec["alignment"] = ALIGN[text[0]]
                                text = text[1:]
                            rec["value"] = text
                    else:
                        flen = struct.unpack_from("<H", pl, 13)[0]
                        if 15 + flen != ln:
                            res.add_damage("bad_length", pos, "formula token length %d inconsistent with record" % flen, True)
                            ok = False
                        else:
                            rec["type"] = "formula"
                            rec["cached_value"] = struct.unpack_from("<d", pl, 5)[0]
                            rec["formula_raw_hex"] = pl[15:].hex()
                    if ok:
                        if nf is not None and rec["type"] != "label":
                            rec["number_format"] = nf
                            if nf.startswith("date:"):
                                v = rec.get("value", rec.get("cached_value"))
                                iso = _iso_date(v) if v is not None else None
                                if iso:
                                    rec["iso_date"] = iso
                        key = (row, col)
                        if key not in cells:
                            order.append(key)
                        cells[key] = rec
        else:
            res.add_damage("unknown_record", pos, "unknown opcode 0x%04x (%d bytes skipped)" % (op, ln), False)
            unverified_any = True
        pos = end
        idx += 1

    if not eof and not any(d["kind"] == "truncated" for d in res.damage):
        res.add_damage("truncated", size, "EOF record missing", True)
    if eof and pos < size:
        res.add_damage("unparsed_bytes", pos, "%d bytes after EOF record" % (size - pos), False)
    if widths:
        res.metadata["column_widths"] = widths
    # non-finite floats cannot be represented in JSON: report them as null and flag
    for key in order:
        rec = cells[key]
        for f in ("value", "cached_value"):
            v = rec.get(f)
            if isinstance(v, float) and v != v or v in (float("inf"), float("-inf")):
                rec[f] = None
                rec["verified"] = False
                rec["issues"] = ["invalid_value"]
                res.add_damage("invalid_value", 0, "cell %s holds a non-finite number" % rec["cell"], True)
        res.records.append(rec)
    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
