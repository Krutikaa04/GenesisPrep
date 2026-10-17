"""Coherent RDW/BDW regions bound EBCDIC output without resynchronization."""
from ._large import budget_issue
from .formats import ebcdic_dump as ebcdic


def resource_issue(data, coarse_reason):
    layout = ebcdic._layout(data[:64])
    if layout not in ("V", "VB"):
        return coarse_reason
    pos, region_end, output, items = 0, len(data) if layout == "V" else 0, 4096, 0
    work = 8 * len(data)
    reason = budget_issue("EBCDIC-DUMP", work, output, items)
    if reason:
        return reason
    while pos < len(data):
        if layout == "VB" and pos == region_end:
            if pos + 4 > len(data) or data[pos+2:pos+4] != b"\0\0":
                return coarse_reason
            length = int.from_bytes(data[pos:pos+2], "big")
            region_end = pos + length
            if length < 9 or region_end > len(data):
                return coarse_reason
            items += 1
            pos += 4
        stop = ebcdic._record_end(data, pos, region_end)
        if stop is None:
            return coarse_reason
        kind = data[pos+4]
        items += 1
        output += 1024 if kind == ebcdic.D else 64
        reason = budget_issue("EBCDIC-DUMP", work, output, items)
        if reason:
            return reason
        pos = stop
    return None
