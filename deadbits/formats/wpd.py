"""Decode the kit's WordPerfect document profile, with bounded WP5 framing.

The kit uses a 48-byte header, a text-end word at 0x22 and a 5.x text
stream despite advertising version 2.0. This is not a general WP6 parser.
WP5 functions C0-CF have individual fixed widths; D0-FF use matching
size/subcode/gate suffixes (size excludes four framing bytes). No function
payload is interpreted as ordinary text after framing damage.
"""
import struct

from ..model import Result, unverified

NAME = "WPD"
MAGIC = b"\xffWPC"
HEADER_LEN = 0x30
MAX_RECORDS = 100_000
MAX_TEXT_BYTES = 8 * 1024 * 1024
# Format facts, independently implemented from the WP5 framing description.
_FIXED_WIDTHS = (4, 9, 11, 3, 3, 5, 6, 7, 4, 5, 6, 6, 8, 10, 10, 12)


def detect(data: bytes) -> float:
    if len(data) < 14 or data[:4] != MAGIC:
        return 0.0
    if data[8:10] == b"\x01\x0a":
        return 1.0
    # Other WPC product/file types are recognised but remain unsupported.
    pointer = struct.unpack_from("<I", data, 4)[0]
    return 0.9 if HEADER_LEN <= pointer <= len(data) else 0.0


def _fn_len(code: int, data: bytes, pos: int):
    if 0xC0 <= code <= 0xCF:
        return _FIXED_WIDTHS[code - 0xC0]
    if 0xD0 <= code <= 0xFF and pos + 4 <= len(data):
        return 4 + struct.unpack_from("<H", data, pos + 2)[0]
    return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if data[:4] != MAGIC:
        res.status = "failed"
        res.add_damage("invalid_value", 0, "WordPerfect signature is missing", True)
        return res
    if size < 14:
        res.status = "failed"
        res.add_damage("truncated", size, "WordPerfect identification header is truncated", True)
        return res
    product, ftype, major, minor = data[8:12]
    key = struct.unpack_from("<H", data, 12)[0]
    res.metadata = {"product_type": product, "file_type": ftype,
                    "version": "%d.%d" % (major, minor), "encrypted": key != 0}
    if key:
        res.status = "unsupported"
        res.add_damage("encrypted", 12, "document is password protected; text not decoded", True)
        return res
    # Only this sample-backed document/header profile is established. Other
    # WPC products and versions must not be treated as the same text stream.
    if product != 1 or ftype != 10 or (major, minor) != (2, 0):
        res.status = "unsupported"
        offset = 8 if product != 1 else 9 if ftype != 10 else 10
        res.add_damage("unknown_record", offset,
                       "unsupported WPC product/file type/version profile", True)
        return res
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res
    doc_ptr = struct.unpack_from("<I", data, 4)[0]
    end_ptr = struct.unpack_from("<H", data, 0x22)[0]
    if not HEADER_LEN <= doc_ptr <= size:
        res.status = "failed"
        res.add_damage("oob_pointer", 4, "document area pointer %d is outside the file" % doc_ptr, True)
        return res
    if end_ptr < doc_ptr:
        res.status = "failed"
        res.add_damage("oob_pointer", 0x22, "text end precedes the document area", True)
        return res
    end = min(size, end_ptr)
    truncated = end_ptr > size
    if truncated:
        res.add_damage("truncated", size, "document declares text up to byte %d but file ends at %d" %
                       (end_ptr, size), True)
    paragraph, issues, idx, pos = [], set(), 0, doc_ptr
    limited = False
    text_limit = min(end, doc_ptr + MAX_TEXT_BYTES)

    def flush(kind="paragraph", extra_issue=None):
        nonlocal idx
        rec = {"index": idx, "type": kind, "text": "".join(paragraph)}
        flags = issues | ({extra_issue} if extra_issue else set())
        if flags:
            unverified(rec, *flags)
        res.records.append(rec)
        idx += 1
        paragraph.clear()
        issues.clear()

    def stop_at_limit():
        nonlocal limited
        limited = True
        res.add_damage("bad_length", pos,
                       "document decode budget exceeded (%d text bytes / %d records); remainder omitted" %
                       (MAX_TEXT_BYTES, MAX_RECORDS), True)
        if paragraph and idx < MAX_RECORDS:
            flush(extra_issue="bad_length")

    while pos < end:
        if idx >= MAX_RECORDS or pos >= text_limit:
            stop_at_limit()
            break
        b = data[pos]
        if b == 0x0A:
            flush()
            pos += 1
        elif b == 0x0C:
            if paragraph:
                flush()
            if idx >= MAX_RECORDS:
                stop_at_limit()
                break
            flush("page_break")
            pos += 1
        elif b in (0x0B, 0x0D, 0xA0):
            paragraph.append(" ")
            pos += 1
        elif b == 0x09:
            paragraph.append("\t")
            pos += 1
        elif b == 0xA9:
            paragraph.append("-")
            pos += 1
        elif b == 0xAA:
            pos += 1  # Retained kit assumption: discretionary hyphen is dropped.
        elif 0x20 <= b < 0x7F:
            paragraph.append(chr(b))
            pos += 1
        elif b >= 0xC0:
            if b >= 0xD0 and pos + 4 > text_limit and text_limit < end:
                stop_at_limit()
                break
            length = None if b >= 0xD0 and pos + 4 > end else _fn_len(b, data, pos)
            if length is not None and pos + length > text_limit and text_limit < end:
                stop_at_limit()
                break
            short_header = length is None
            overrun = length is not None and pos + length > end
            valid = not short_header and not overrun and length >= (8 if b >= 0xD0 else 3)
            if valid:
                stop = pos + length
                valid = data[stop - 1] == b
                if valid and b >= 0xD0:
                    valid = (data[stop - 2] == data[pos + 1] and
                             data[stop - 4:stop - 2] == data[pos + 2:pos + 4])
            if not valid:
                # A function's payload can contain ASCII, returns and gates.
                # Without valid framing there is no safe later text boundary.
                kind = "truncated" if (short_header or overrun) else "bad_length"
                if kind != "truncated" or not truncated:
                    res.add_damage(kind, pos, "function 0x%02x cannot be safely delimited; remaining text omitted" % b, True)
                issues.add(kind)
                if paragraph:
                    flush(extra_issue=kind)
                break
            if b == 0xC0:
                # Extended-character tables are not established by the kit.
                paragraph.append("\ufffd")
                issues.add("unknown_record")
                res.add_damage("unknown_record", pos, "extended WordPerfect character is unsupported", True)
            elif b not in (0xC3, 0xC4):
                # Delimiters prove where a function ends, not that its payload
                # is decoration. Unseen groups can carry footnotes or other
                # text; skipping them is an explicit, unverified omission.
                issues.add("unknown_record")
                res.add_damage("unknown_record", pos,
                               "function 0x%02x is delimited but its semantic content is unsupported" % b, True)
            pos += length
        else:
            # Unknown character sets/control functions cannot establish a
            # Unicode character. Preserve the location without guessing Latin-1.
            if "invalid_value" not in issues:
                res.add_damage("invalid_value", pos, "unsupported text byte 0x%02x" % b, True)
            issues.add("invalid_value")
            paragraph.append("\ufffd")
            pos += 1
    else:
        if paragraph:
            flush(extra_issue="truncated" if truncated else None)
    if limited:
        res.status = "partial"
    elif not res.records and res.damage:
        res.status = "failed"
    elif res.damage:
        res.status = "partial"
    return res
