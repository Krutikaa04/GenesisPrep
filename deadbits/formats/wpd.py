"""WPD: WordPerfect 5.x-style document (government office, early 1990s).

Layout, derived from s14/s15 (no reference output exists; text rules below are ASSUMPTIONS, see FORMAT-SPEC):

  header : FF 'W' 'P' 'C' | doc_area u32 | product u8 | file_type u8 | major u8 | minor u8
           | encryption_key u16 (non-zero => password protected) | index_ptr u16 | ...
           u16 at 0x22 = absolute end of the document text (s14: file continues with summary strings;
           s15: points past EOF => the file is truncated)
  text   : 0x0A hard return (paragraph end)   0x0D soft return (-> space)   0x0C hard page break
           0x09 tab   0xA0 hard space (-> space)   0xA9 hyphen (-> '-')   0xAA soft hyphen (dropped)
           0xC0-0xCF  code, 1 byte, code            (3 bytes; e.g. C3 0C C3 = bold on)
           0xD0-0xDF  code, 2 bytes, code           (4 bytes)
           0xE0-0xEF  code, 4 bytes, code           (6 bytes)
           0xF0-0xFF  code, subcode, len u16, data[len-?]... code   (variable; length field at +2 counts the data)
"""
import struct

from ..model import Result, unverified

NAME = "WPD"
MAGIC = b"\xffWPC"
HEADER_LEN = 0x30


def detect(data: bytes) -> float:
    return 1.0 if data[:4] == MAGIC else 0.0


def _fn_len(code: int, data: bytes, pos: int):
    if 0xC0 <= code <= 0xCF:
        return 3
    if 0xD0 <= code <= 0xDF:
        return 4
    if 0xE0 <= code <= 0xEF:
        return 6
    if code >= 0xF0 and pos + 4 <= len(data):
        return 4 + struct.unpack_from("<H", data, pos + 2)[0] + 1
    return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res
    doc_ptr = struct.unpack_from("<I", data, 4)[0]
    product, ftype, major, minor = data[8], data[9], data[10], data[11]
    key = struct.unpack_from("<H", data, 12)[0]
    end_ptr = struct.unpack_from("<H", data, 0x22)[0]
    res.metadata = {"product_type": product, "file_type": ftype, "version": "%d.%d" % (major, minor),
                    "encrypted": key != 0}
    if key != 0:
        res.status = "unsupported"
        res.add_damage("encrypted", 12, "document is password protected (key 0x%04x); text not decoded" % key, True)
        return res
    if doc_ptr < HEADER_LEN or doc_ptr > size:
        res.status = "failed"
        res.add_damage("oob_pointer", 4, "document area pointer %d is outside the file (size %d)" % (doc_ptr, size), True)
        return res

    end = size
    truncated = False
    if end_ptr >= doc_ptr:
        if end_ptr > size:
            truncated = True
            res.add_damage("truncated", size, "document declares text up to byte %d but file ends at %d" %
                           (end_ptr, size), True)
        else:
            end = end_ptr
    paragraph, idx, pos = [], 0, doc_ptr
    pending = False
    unverified_any = False

    def flush(kind="paragraph", flag=False):
        nonlocal idx
        rec = {"index": idx, "type": kind, "text": "".join(paragraph)}
        if flag:
            unverified(rec, "truncated")
        res.records.append(rec)
        idx += 1
        paragraph.clear()

    while pos < end:
        b = data[pos]
        if b == 0x0A:
            flush()
            pos += 1
        elif b == 0x0C:
            if paragraph:
                flush()
            res.records.append({"index": idx, "type": "page_break", "text": ""})
            idx += 1
            pos += 1
        elif b == 0x0D:
            paragraph.append(" ")
            pos += 1
        elif b == 0x09:
            paragraph.append("\t")
            pos += 1
        elif b == 0xA0:
            paragraph.append(" ")
            pos += 1
        elif b == 0xA9:
            paragraph.append("-")
            pos += 1
        elif b == 0xAA:
            pos += 1
        elif 0x20 <= b < 0x7F:
            paragraph.append(chr(b))
            pos += 1
        elif b >= 0xC0:
            ln = _fn_len(b, data, pos)
            if ln is None or pos + ln > end or data[pos + ln - 1] != b:
                res.add_damage("unknown_record", pos, "function code 0x%02x at %d could not be delimited" % (b, pos), False)
                unverified_any = True
                pos += 1
            else:
                pos += ln
        else:
            pos += 1     # other control bytes carry no text
    if paragraph:
        flush(flag=truncated)
        if truncated:
            unverified_any = True
    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
