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
MIN_TRAILER = 4          # smallest trailer recognition accepts; both kit trailers are 15+ bytes
MAX_RECORDS = 100_000
MAX_TEXT_BYTES = 8 * 1024 * 1024
_PREFIX = re.compile(br"[ -~\r\n\t]*")
_BAD_TEXT = re.compile(br"[^ -~\t\n]")
# Damaged text is accepted only with the intact marker + trailer as proof and mostly-text content.
_TEXT_BYTE = re.compile(br"[ -~\r\n\t]")
MIN_TEXT_FRACTION = 0.7
# Truncated-file recognition (no trailer to prove the layout): see _truncated_score.
_TRUNCATED_TEXT = re.compile(br"[ -~\r\t]*")
MIN_TRUNCATED_TEXT = 32
MIN_TRUNCATED_CRS = 3
MAX_TRUNCATED_SIZE = 64 * 1024     # the engine only shows detect() this much of a larger file
_BAD_CONTROLS = {b: "\ufffd" for b in range(32) if b not in (9, 10)}
_BAD_CONTROLS[127] = "\ufffd"


def _prefix_ok(buf: bytes) -> bool:
    return _PREFIX.fullmatch(buf) is not None


def _truncated_score(data: bytes, p: int) -> float:
    """Low-confidence recognition of a BRAVO file cut before its trailer was complete.

    No marker/trailer proof exists, so the text itself must look like Bravo output: only printable ASCII, TAB and
    CR (no LF, which rules out DOS and Unix text), at least MIN_TRUNCATED_CRS CR-terminated paragraphs and a
    bounded size. Plain CR-delimited text from another source would still match: this is a documented
    assumption, which is why the score stays barely above the engine threshold.
    """
    if len(data) >= MAX_TRUNCATED_SIZE:
        return 0.0
    if p >= 0:
        tail = data[p + 1:]
        # A cut trailer is a few leading control bytes; text or a second marker is something else.
        if p < 8 or data[p - 1] != 13 or any(not (b < 32 and b not in (9, 10, 13, 26)) for b in tail):
            return 0.0
        text = data[:p]
    else:
        text = data
    if len(text) < MIN_TRUNCATED_TEXT or text.count(b"\r") < MIN_TRUNCATED_CRS:
        return 0.0
    return 0.55 if _TRUNCATED_TEXT.fullmatch(text) else 0.0


def detect(data: bytes) -> float:
    # A complete marker/trailer must fit the bounded recognition window.
    p = data.find(b"\x1a", 0, MAX_TEXT_BYTES + 1)
    trailer_size = len(data) - p - 1
    if p < 0 or trailer_size < 4:
        return _truncated_score(data, p)
    if p < 8 or trailer_size > MAX_TRAILER:
        return 0.0
    # A second delimiter or purely textual/empty DOS EOF suffix is not proof.
    trailer = data[p + 1:]
    if (b"\x1a" in trailer or trailer.count(b"\x00") < 2 or
            not any(0 < b < 32 and b not in (9, 10, 13, 26) for b in trailer)):
        return 0.0
    if data[p - 1] != 13:
        return 0.0
    if _PREFIX.fullmatch(data, 0, p):
        return 0.8
    # The trailer proves the layout, so damaged text still identifies the file. The paragraph bytes are only
    # required to be mostly text: random binary data cannot reach this fraction over a realistic length.
    good = len(_TEXT_BYTE.findall(data, 0, p))
    return 0.6 if good >= MIN_TEXT_FRACTION * p else 0.0


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    marker = data.find(b"\x1a", 0, MAX_TEXT_BYTES + 1)
    end = min(len(data), MAX_TEXT_BYTES) if marker < 0 else marker
    text_limited = marker < 0 and len(data) > MAX_TEXT_BYTES
    if marker < 0 and not text_limited:
        res.add_damage("truncated", end, "end-of-text marker 0x1A not found; trailer lost", True)
    elif 0 <= marker and len(data) - marker - 1 < MIN_TRAILER:
        # Shorter than any trailer recognition accepts: the file was cut inside it.
        res.add_damage("truncated", len(data), "file ends inside the formatting trailer", True)
    # Scan without making a second list of all paragraphs. Empty CR-delimited
    # paragraphs are real records, including a leading blank paragraph.
    start = index = 0
    limited = text_limited
    numbering_lost = False       # an earlier damaged paragraph may have swallowed CR delimiters
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
        if numbering_lost:
            unverified(rec, "invalid_value")
        elif invalid is not None:
            # Damaged bytes may have been delimiters: later paragraph numbers are no longer provable.
            numbering_lost = True
            res.add_damage("invalid_value", start + invalid.start(),
                           "paragraph numbering after this point cannot be verified (damaged bytes may have "
                           "hidden CR delimiters)", False)
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
