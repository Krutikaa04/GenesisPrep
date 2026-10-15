"""EBCDIC-DUMP: university mainframe tape extract (1999), variable-length records in cp037.

Layout, derived from s20-s22 and confirmed on s20 (expected_outputs):

  RECFM=V  : records are  RDW (u16 BE length incl. the 4 RDW bytes, u16 zero) + data
  RECFM=VB : same, but wrapped in blocks that start with a 4-byte BDW (u16 BE block length, u16 zero)
  H header : 'H' | title char[20] | run date char[8] YYYYMMDD
  D data   : 'D' | student_id char[6] | name char[20] | dob packed(5, 0YYYYMMDD) | gpa packed(3, /100)
             | credits u16 BE | status char | balance packed(4, /100) | 2 filler bytes      (43 bytes after the type char)
  T trailer: 'T' | record count packed(4) | credits total packed(5)
"""
import datetime

from ..model import Result, unverified

NAME = "EBCDIC-DUMP"
H, D, T = 0xC8, 0xC4, 0xE3
D_LEN = 43


def _packed(b: bytes):
    """Packed-decimal -> int, or None when a nibble is not a digit / the sign nibble is invalid."""
    digits = []
    for x in b[:-1]:
        hi, lo = x >> 4, x & 0xF
        if hi > 9 or lo > 9:
            return None
        digits += [hi, lo]
    hi, sign = b[-1] >> 4, b[-1] & 0xF
    if hi > 9 or sign < 0xA:
        return None
    digits.append(hi)
    n = int("".join(map(str, digits)))
    return -n if sign in (0xB, 0xD) else n


def _layout(data: bytes):
    """-> 'V', 'VB' or None."""
    if len(data) >= 5 and data[2:4] == b"\0\0" and data[4] == H:
        return "V"
    if len(data) >= 9 and data[2:4] == b"\0\0" and data[6:8] == b"\0\0" and data[8] == H:
        return "VB"
    return None


def detect(data: bytes) -> float:
    lay = _layout(data)
    if lay is None:
        return 0.0
    off = 4 if lay == "V" else 8
    ln = int.from_bytes(data[off - 4:off - 2], "big")
    return 1.0 if 5 <= ln <= len(data) - (off - 4) and ln >= 29 else 0.7


def _iso8(text: str):
    try:
        return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
    except ValueError:
        return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    lay = _layout(data) or "V"
    pos = 0
    blocks_end = None
    unverified_any = False
    truncated = False
    trailer = None
    d_count = credits_sum = 0

    while pos < size:
        if lay == "VB" and (blocks_end is None or pos >= blocks_end):
            if pos + 4 > size:
                res.add_damage("truncated", pos, "file ends inside a block descriptor", True)
                truncated = True
                break
            bl = int.from_bytes(data[pos:pos + 2], "big")
            if bl < 8:
                res.add_damage("bad_length", pos, "block length %d is impossible" % bl, True)
                res.add_damage("unparsed_bytes", pos, "%d bytes after unreadable block descriptor" % (size - pos), True)
                break
            blocks_end = min(pos + bl, size)
            pos += 4
            continue
        if pos + 4 > size:
            res.add_damage("truncated", pos, "file ends inside a record descriptor", True)
            truncated = True
            break
        ln = int.from_bytes(data[pos:pos + 2], "big")
        zero = data[pos + 2:pos + 4]
        if ln < 5 or zero != b"\0\0":
            res.add_damage("bad_length", pos, "record descriptor invalid (length %d)" % ln, True)
            res.add_damage("unparsed_bytes", pos, "%d bytes after unreadable record descriptor" % (size - pos), True)
            unverified_any = True
            break
        end = pos + ln
        if end > size:
            res.add_damage("truncated", pos, "record needs %d bytes but only %d remain" % (ln, size - pos), True)
            truncated = True
            break
        rec = data[pos + 4:end]
        kind = rec[0]
        if kind == H:
            if len(rec) >= 29:
                res.metadata["title"] = rec[1:21].decode("cp037", "replace").rstrip()
                res.metadata["run_date"] = _iso8(rec[21:29].decode("cp037", "replace"))
            else:
                res.add_damage("bad_length", pos, "header record is %d bytes, expected 29" % len(rec), False)
                unverified_any = True
        elif kind == D:
            if len(rec) != 1 + D_LEN:
                res.add_damage("bad_length", pos, "data record is %d bytes, expected %d" % (len(rec), 1 + D_LEN), True)
                unverified_any = True
            else:
                body = rec[1:]
                issues = []
                dob_n = _packed(body[26:31])
                dob = None
                if dob_n is not None and 0 <= dob_n <= 99999999:
                    dob = _iso8("%08d" % dob_n)
                if dob is None:
                    issues.append("invalid_value")
                gpa_n, bal_n = _packed(body[31:34]), _packed(body[37:41])
                if gpa_n is None or bal_n is None:
                    issues.append("invalid_value")
                credits = int.from_bytes(body[34:36], "big")
                out = {
                    "student_id": body[0:6].decode("cp037", "replace"),
                    "name": body[6:26].decode("cp037", "replace").rstrip(),
                    "dob": dob,
                    "gpa": None if gpa_n is None else round(gpa_n / 100, 2),
                    "credits": credits,
                    "status": body[36:37].decode("cp037", "replace"),
                    "balance": None if bal_n is None else round(bal_n / 100, 2),
                }
                if issues:
                    unverified(out, *issues)
                    unverified_any = True
                    res.add_damage("invalid_value", pos, "record %s has undecodable packed fields" % out["student_id"], True)
                res.records.append(out)
                d_count += 1
                credits_sum += credits
        elif kind == T:
            c, tot = _packed(rec[1:5]), _packed(rec[5:10])
            if len(rec) >= 10 and c is not None and tot is not None:
                trailer = (c, tot)
                res.metadata["trailer_count"] = c
                res.metadata["trailer_credits_total"] = tot
            else:
                res.add_damage("bad_length", pos, "trailer record malformed", False)
                unverified_any = True
        else:
            res.add_damage("unknown_record", pos, "unknown record type 0x%02x (%d bytes skipped)" % (kind, ln), False)
            unverified_any = True
        pos = end

    if trailer is not None and not truncated:
        if trailer[0] != d_count:
            res.add_damage("count_mismatch", 0, "trailer says %d records, %d found" % (trailer[0], d_count),
                           d_count < trailer[0])
        if trailer[1] != credits_sum:
            res.add_damage("checksum_mismatch", 0, "trailer credits total %d, records sum to %d" %
                           (trailer[1], credits_sum), False)
    elif trailer is None and not truncated:
        res.add_damage("truncated", size, "trailer record missing", True)
    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
