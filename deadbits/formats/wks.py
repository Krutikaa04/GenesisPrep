"""WKS: Lotus 1-2-3 worksheet saved on a DOS PC (early 1990s).

Record stream (little-endian): opcode u16 | length u16 | payload.  Layout confirmed on s11 (expected
output) and s12/s13 (structure only):

  0x0000 BOF  version u16 (0x0404)           0x0001 EOF
  0x0006 RANGE c0 r0 c1 r1 (4 x u16)         0x0008 COLW  col u16, width u8
  0x0002-0x0005, 0x0007, 0x000B  settings / window / named range (known, not decoded)
  0x000C BLANK   fmt u8, col u16, row u16
  0x000D INTEGER fmt, col, row, i16          0x000E NUMBER fmt, col, row, f64
  0x000F LABEL   fmt, col, row, text\\0 (first char = alignment prefix ' \" ^ \\\\ )
  0x0010 FORMULA fmt, col, row, f64 cached value, u16 token length, tokens
  fmt: 0xFF = default; high nibble 0 fixed, 1 scientific, 2 currency, 3 percent, 4 comma, 7 special
       (0x71-0x75 date formats); low nibble = decimals.
Any other opcode is skipped by its length and reported as `unknown_record`.
A cell written more than once keeps its LAST value (assumption; documented in FORMAT-SPEC).

Damage handling (M2): the stream has no resync marker, so a corrupted length field would silently
swallow or desynchronise every later record.  Each record is therefore checked against the layout above:
  * a fixed-length opcode (BOF/RANGE/COLW/BLANK/INTEGER/NUMBER and the settings records) whose declared
    length differs from the known length is repaired ONLY when a strict chain of valid records follows at
    the known length (cell kept, flagged unverified + bad_length);
  * otherwise the decoder scans forward for the first offset where >= 3 consecutive strictly valid records
    (or a valid record chain ending in EOF exactly at end of file) start; the skipped bytes are reported
    as lossy `unparsed_bytes` and decoding continues there;
  * if no such offset exists the file is reported as `truncated` (record runs past EOF) or the remainder
    is reported as unparsed, and decoding stops.  Nothing is ever guessed.
"""
import datetime
import struct

from ..model import Result, unverified

NAME = "WKS"
KNOWN_META = {0x02, 0x03, 0x04, 0x05, 0x07, 0x0B}
MAX_COL, MAX_ROW = 255, 8191
ALIGN = {"'": "left", '"': "right", "^": "center", "\\": "repeat"}
FMT_TYPES = {0: "fixed", 1: "scientific", 2: "currency", 3: "percent", 4: "comma"}
FIXED_LEN = {0x0C: 5, 0x0D: 7, 0x0E: 13}
# Known payload lengths of the non-cell records, taken from s11/s12 (all 3 kit files agree).
HEAD_LEN = {0x00: 2, 0x01: 0, 0x06: 8, 0x08: 3, 0x02: 1, 0x03: 1, 0x04: 1, 0x05: 1, 0x07: 31, 0x0B: 24}
EXPECT_LEN = {**HEAD_LEN, **FIXED_LEN}
CELL_OPS = (0x0C, 0x0D, 0x0E, 0x0F, 0x10)
CHAIN_NEED = 3


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
    """Only date/time formats are emitted (the s11 reference carries no number_format for currency cells)."""
    if fmt == 0xFF:
        return None
    t, d = fmt >> 4, fmt & 0xF
    if t != 7:
        return None
    return {1: "date:D1", 2: "date:D2", 3: "date:D3", 4: "date:D4", 5: "date:D5",
            6: "time:T1", 7: "time:T2", 8: "time:T3", 9: "time:T4"}.get(d, "special:%d" % d)


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


def _payload_ok(op: int, pl: bytes) -> bool:
    """Is the payload self-consistent for this opcode (layout only, no value checks)?"""
    ln = len(pl)
    if op in EXPECT_LEN:
        return ln == EXPECT_LEN[op]
    if op == 0x0F:
        body = pl[5:]
        return ln >= 6 and body[-1:] == b"\x00" and b"\x00" not in body[:-1]
    if op == 0x10:
        return ln >= 15 and 15 + struct.unpack_from("<H", pl, 13)[0] == ln
    return False


def _strict_record(data: bytes, p: int):
    """Strict validity of ONE record at p -> (end, opcode) or None.  Used to find real record boundaries."""
    if p + 4 > len(data):
        return None
    op, ln = struct.unpack_from("<HH", data, p)
    end = p + 4 + ln
    if end > len(data):
        return None
    pl = data[p + 4:end]
    if op in CELL_OPS:
        if not _payload_ok(op, pl):
            return None
        col, row = struct.unpack_from("<HH", pl, 1)
        if col > MAX_COL or row > MAX_ROW:
            return None
    elif op in EXPECT_LEN:
        if ln != EXPECT_LEN[op]:
            return None
    elif op > 0xFF or ln > 256:      # unknown opcodes: accepted only when they look like small records
        return None
    return end, op


def _chain_ok(data: bytes, p: int) -> bool:
    """>= CHAIN_NEED consecutive strict records from p, or strict records ending in EOF exactly at EOF."""
    count = 0
    while p <= len(data):
        if p == len(data):
            return count >= CHAIN_NEED
        rec = _strict_record(data, p)
        if rec is None:
            return False
        p, op = rec
        count += 1
        if op == 0x0001:
            return p == len(data) and count >= 2 or count >= CHAIN_NEED
        if count >= CHAIN_NEED:
            return True
    return False


def _resync(data: bytes, start: int):
    """First offset >= start where a strict record chain begins, else None."""
    for p in range(start, len(data) - 3):
        if _chain_ok(data, p):
            return p
    return None


def _cell(op: int, pl: bytes, pos: int, res: Result):
    """Decode one cell record -> (record or None)."""
    fmt, col, row = struct.unpack_from("<BHH", pl, 0)
    if col > MAX_COL or row > MAX_ROW:
        res.add_damage("invalid_value", pos, "cell position col %d row %d outside worksheet" % (col, row), True)
        return None
    rec = {"cell": "%s%d" % (col_letters(col), row + 1), "col": col, "row": row}
    nf = _number_format(fmt)
    if op == 0x0C:
        rec["type"] = "blank"
    elif op == 0x0D:
        rec["type"] = "integer"
        rec["value"] = struct.unpack_from("<h", pl, 5)[0]
    elif op == 0x0E:
        rec["type"] = "number"
        rec["value"] = struct.unpack_from("<d", pl, 5)[0]
    elif op == 0x0F:
        text = pl[5:-1].decode("latin-1")
        rec["type"] = "label"
        if text[:1] in ALIGN:
            rec["alignment"] = ALIGN[text[0]]
            text = text[1:]
        rec["value"] = text
    else:
        rec["type"] = "formula"
        rec["cached_value"] = struct.unpack_from("<d", pl, 5)[0]
        rec["formula_raw_hex"] = pl[15:].hex()
    if nf is not None and rec["type"] != "label":
        rec["number_format"] = nf
        if nf.startswith("date:"):
            v = rec.get("value", rec.get("cached_value"))
            iso = _iso_date(v) if v is not None else None
            if iso:
                rec["iso_date"] = iso
    return rec


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    pos, idx, eof, unverified_any = 0, 0, False, False
    cells = {}          # (row, col) -> record, keeps last write; order of first appearance preserved separately
    order = []
    widths = {}
    stopped = False

    def keep(rec, *issues):
        nonlocal unverified_any
        if issues:
            unverified(rec, *issues)
            unverified_any = True
        key = (rec["row"], rec["col"])
        if key not in cells:
            order.append(key)
        cells[key] = rec

    while pos < size:
        if pos + 4 > size:
            res.add_damage("truncated", pos, "file ends inside a record header (%d bytes left)" % (size - pos), True)
            stopped = True
            break
        op, ln = struct.unpack_from("<HH", data, pos)
        end = pos + 4 + ln
        repaired = False                      # declared length was wrong but the real one is known and verified
        structure_ok = end <= size
        if op in EXPECT_LEN and ln != EXPECT_LEN[op]:
            # Known opcode with an odd length.  The known length wins when the stream after it is coherent;
            # an odd length is accepted only for non-cell records whose declared end is coherent instead.
            true_end = pos + 4 + EXPECT_LEN[op]
            if true_end <= size and _chain_ok(data, true_end):
                res.add_damage("bad_length", pos, "record 0x%04x declares length %d; known length %d restored "
                               "(next records verified)" % (op, ln, EXPECT_LEN[op]), False)
                repaired, end, ln, structure_ok = True, true_end, EXPECT_LEN[op], True
            else:
                structure_ok = structure_ok and op not in CELL_OPS and _chain_ok(data, end)
        elif structure_ok and op in (0x0F, 0x10) and not _payload_ok(op, data[pos + 4:end]):
            structure_ok = False
        if not structure_ok:
            nxt = _resync(data, pos + 1)
            if nxt is None:
                if end > size:
                    res.add_damage("truncated", pos, "record 0x%04x declares %d bytes but only %d remain" %
                                   (op, ln, size - pos - 4), True)
                else:
                    res.add_damage("bad_length", pos, "record 0x%04x has an inconsistent length (%d) and no "
                                   "valid record follows" % (op, ln), True)
                    res.add_damage("unparsed_bytes", pos, "%d bytes could not be parsed" % (size - pos), True)
                stopped = True
                break
            res.add_damage("bad_length", pos, "record 0x%04x has an inconsistent length (%d)" % (op, ln), True)
            res.add_damage("unparsed_bytes", pos, "%d bytes skipped to re-synchronise at offset %d" %
                           (nxt - pos, nxt), True)
            unverified_any = True
            pos, idx = nxt, idx + 1
            continue

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
        elif op in CELL_OPS:
            rec = _cell(op, pl, pos, res)
            if rec is not None:
                keep(rec, *(("bad_length",) if repaired else ()))
        else:
            res.add_damage("unknown_record", pos, "unknown opcode 0x%04x (%d bytes skipped)" % (op, ln), False)
            unverified_any = True
        pos = end
        idx += 1

    if not eof and not stopped and not any(d["kind"] == "truncated" for d in res.damage):
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
            if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
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
