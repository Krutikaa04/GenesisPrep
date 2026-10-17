"""Bound CRC-valid LABLOG blocks and retained samples/events before decoding."""
import binascii
import math
import struct

from ._large import budget_issue


def resource_issue(data, coarse_reason):
    if len(data) < 32 or data[:4] != b"LLOG" or not data[5]:
        return coarse_reason
    if binascii.crc_hqx(memoryview(data)[:30], 65535) != struct.unpack_from("<H", data, 30)[0]:
        return coarse_reason  # do not enter damaged-header channel inference
    channels = data[5]
    work, output, items = 8 * len(data), 4096 + 64 * channels, 0
    reason = budget_issue("LABLOG", work, output, items)
    if reason:
        return reason
    pos, blocks, table = 32, 0, False
    while pos < len(data):
        if pos + 6 > len(data) or data[pos] != 0xB1:
            return coarse_reason
        typ = data[pos + 1]
        length = struct.unpack_from("<H", data, pos + 2)[0]
        end = pos + 6 + length
        if end > len(data):
            return coarse_reason
        blocks += 1
        items += 1
        if typ == 3:
            if table or length != 12 * channels:
                return coarse_reason
            for channel in range(channels):
                scale, offset = struct.unpack_from("<ff", data, pos + 8 + 12 * channel)
                if not math.isfinite(scale) or not math.isfinite(offset):
                    return coarse_reason
            table = True
        elif typ == 1:
            if not table or length < 3:
                return coarse_reason
            samples = data[pos + 6]
            if length != 3 + 2 * samples * channels:
                return coarse_reason
            items += samples
            work += 16 * samples * channels
            output += samples * (512 + 32 * channels)
        elif typ == 2:
            if length < 4 or length != 4 + data[pos + 7]:
                return coarse_reason
            items += 1
            output += 512 + 4 * (length - 4)
        else:
            return coarse_reason
        reason = budget_issue("LABLOG", work, output, items)
        if reason:
            return reason
        if binascii.crc_hqx(memoryview(data)[pos + 1:end - 2], 65535) != struct.unpack_from("<H", data, end - 2)[0]:
            return coarse_reason  # no large-input resync/overlapping CRC repair
        pos = end
    return None if blocks == struct.unpack_from("<H", data, 28)[0] else coarse_reason
