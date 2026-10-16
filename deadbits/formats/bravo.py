"""Decode the kit's Bravo CR paragraphs; formatting-run trailer is unproved.

With no signature, recognition needs a terminated ASCII text prefix plus a
short binary trailer containing NULs and non-whitespace control bytes. Plain
DOS text ending at 1A alone is insufficient evidence. The trailer's semantics
are intentionally not inferred from two incompatible-looking examples.
"""
import re

from ..model import Result, unverified

NAME = "BRAVO"
MAX_TRAILER = 512
MAX_RECORDS = 100_000
MAX_TEXT_BYTES = 8 * 1024 * 1024
_PREFIX = re.compile(br"[ -~\r\n\t]*")
_BAD_TEXT = re.compile(br"[^ -~\t\n]")
_BAD_CONTROLS = {b: "\ufffd" for b in range(32) if b not in (9, 10)}
_BAD_CONTROLS[127] = "\ufffd"


def _prefix_ok(buf: bytes) -> bool:
    return _PREFIX.fullmatch(buf) is not None


def detect(data: bytes) -> float:
    # A complete marker/trailer must fit the bounded recognition window.
    p = data.find(b"\x1a", 0, MAX_TEXT_BYTES + 1)
    trailer_size = len(data) - p - 1
    if p < 8 or not 4 <= trailer_size <= MAX_TRAILER:
        return 0.0
    # A second delimiter or purely textual/empty DOS EOF suffix is not proof.
    trailer = data[p + 1:]
    if (b"\x1a" in trailer or trailer.count(b"\x00") < 2 or
            not any(0 < b < 32 and b not in (9, 10, 13, 26) for b in trailer)):
        return 0.0
    return 0.8 if data[p - 1] == 13 and _PREFIX.fullmatch(data, 0, p) else 0.0


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    marker = data.find(b"\x1a", 0, MAX_TEXT_BYTES + 1)
    end = min(len(data), MAX_TEXT_BYTES) if marker < 0 else marker
    text_limited = marker < 0 and len(data) > MAX_TEXT_BYTES
    if marker < 0 and not text_limited:
        res.add_damage("truncated", end, "end-of-text marker 0x1A not found; trailer lost", True)
    # Scan without making a second list of all paragraphs. Empty CR-delimited
    # paragraphs are real records, including a leading blank paragraph.
    start = index = 0
    limited = text_limited
    while start < end:
        if index >= MAX_RECORDS:
            limited = True
            break
        stop = data.find(b"\r", start, end)
        terminated = stop >= 0
        if not terminated:
            stop = end
        raw = data[start:stop]
        invalid = _BAD_TEXT.search(raw)
        text = raw.decode("ascii", "replace").translate(_BAD_CONTROLS)
        rec = {"index": index, "text": text}
        if invalid is not None:
            unverified(rec, "invalid_value")
            res.add_damage("invalid_value", start + invalid.start(),
                           "paragraph contains unsupported non-ASCII/control bytes", True)
        if not terminated:
            unverified(rec, "bad_length" if text_limited else "truncated")
            if marker >= 0:
                res.add_damage("invalid_value", end, "final paragraph is not CR-terminated", True)
        res.records.append(rec)
        index += 1
        start = stop + 1
    if limited:
        res.add_damage("bad_length", min(start, end),
                       "document decode budget exceeded (%d text bytes / %d records); remainder omitted" %
                       (MAX_TEXT_BYTES, MAX_RECORDS), True)
        res.status = "partial"
    elif not res.records and res.damage:
        res.status = "failed"
    elif res.damage:
        res.status = "partial"
    return res
