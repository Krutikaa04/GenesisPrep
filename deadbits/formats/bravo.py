"""BRAVO: Xerox Alto "Bravo" editor document (1970s research lab).

No magic number. Layout inferred from s16/s17: the text, CR (0x0D) terminated paragraphs, then 0x1A,
then a binary trailer of formatting runs ("looks"). The trailer is bonus data and is NOT validated
(its structure could not be confirmed on two samples), so a malformed trailer never produces damage.
Detection is structural: a printable-ASCII prefix containing CRs, a single 0x1A, a short trailer.
"""
from ..model import Result, unverified

NAME = "BRAVO"
MAX_TRAILER = 512


def _prefix_ok(buf: bytes) -> bool:
    return all(32 <= b < 127 or b in (0x0D, 0x0A, 0x09) for b in buf)


def detect(data: bytes) -> float:
    p = data.find(b"\x1a")
    if p < 8 or len(data) - p > MAX_TRAILER:
        return 0.0
    head = data[:p]
    if b"\r" in head and _prefix_ok(head) and data.count(b"\x1a") <= 1:
        return 0.8
    return 0.0


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    p = data.find(b"\x1a")
    text = data if p < 0 else data[:p]
    if p < 0:
        res.add_damage("truncated", len(data), "end-of-text marker 0x1A not found; trailer lost", True)
    parts = text.split(b"\r")
    unterminated = parts[-1]          # bytes after the last CR (empty when the text ends with CR)
    paragraphs = parts[:-1]
    for i, para in enumerate(paragraphs):
        res.records.append({"index": i, "text": para.decode("latin-1")})
    if unterminated:
        rec = {"index": len(paragraphs), "text": unterminated.decode("latin-1")}
        res.records.append(unverified(rec, "truncated"))
        if p >= 0:
            res.add_damage("invalid_value", p, "final paragraph is not CR-terminated", False)
    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage:
        res.status = "partial"
    return res
