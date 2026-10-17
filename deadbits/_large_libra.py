"""Bound a complete LIBRA chain before permitting the ordinary recovery parser."""
import struct
from ._large import budget_issue
from .formats import libra98


def resource_issue(data, coarse_reason):
    if len(data) < 22 or data[:4] != b"LB98" or data[4] != 2 or data[-6:-2] != b"END!":
        return coarse_reason
    pos = struct.unpack_from("<H", data, 12)[0]
    if not 16 <= pos <= len(data) - 6:
        return coarse_reason
    declared = struct.unpack_from("<H", data, 6)[0]
    enc = "cp1252" if data[5] & 1 else "cp437"
    work, output, count = 8 * len(data), 1536, 0
    reason = budget_issue("LIBRA-98", work, output, count)
    if reason:
        return reason
    while pos < len(data) - 6:
        if pos + 2 > len(data) - 6 or data[pos] != 0xA5:
            return coarse_reason
        length = data[pos + 1]
        end = pos + 2 + length
        if length < libra98.RECORD_MIN or end > len(data) - 6:
            return coarse_reason
        count += 1
        output += 1024 + 4 * length
        reason = budget_issue("LIBRA-98", work, output, count)
        if reason:
            return reason
        # One <=255-byte record at a time; no aggregate is retained. Reusing
        # the owner's checked fields/checksum rules proves _valid_chain will
        # take the decoder's linear path, not its damaged-pointer search.
        record, parsed_end, issues = libra98._parse_record(data, pos, enc)
        if not record or issues or parsed_end != end:
            return coarse_reason
        pos = end
    return None if count == declared else coarse_reason
