"""Conservative preflight budgets for legacy adapters with local accumulators.

These checks bound work before decoding, rather than truncating bytes and
passing an incomplete input off as complete. They deliberately may refuse a
large, valid file. Directory declarations remain hostile; no payload is decoded
and no declared output length is trusted as an allocation/work bound.
"""
import struct

MAX_LEGACY_INPUT_BYTES = 2 * 1024 * 1024
MAX_STRUCTURAL_ITEMS = 100_000
MAX_VAULT_WORK_BYTES = 16 * 1024 * 1024
MAX_VAULT_OUTPUT_BYTES = 16 * 1024 * 1024

# VAULT output can repeat a 255-byte name for each entry. Charge every record
# a fixed allowance including four-byte Unicode name characters and fields.
# This is a conservative projection, not a Python allocator size measurement.
VAULT_ENTRY_OUTPUT_CHARGE = 1536
LEGACY_FORMATS = frozenset(("LIBRA-98", "LABLOG", "EBCDIC-DUMP", "VAULT", "WKS", "CVT"))

# These minimum byte costs include hostile records, not just successful data.
# WKS may emit damage for each four-byte unknown opcode, EBCDIC for each
# five-byte unknown RDW, and LABLOG may emit one sample per two payload bytes.
MIN_ITEM_BYTES = {"WKS": 4, "EBCDIC-DUMP": 5, "LABLOG": 2}


def _vault_rle_projection(data, start, end, key=None):
    """Count RLE90 output without constructing it, including invalid prefixes.

    key selects the XOR-before-RLE candidate; positions are relative to the
    stored payload. Invalid streams still incur all allocation/work up to the
    failing byte. The declared decoded size never bounds this computation.
    """
    size, previous, pos = 0, False, start
    while pos < end:
        byte = data[pos]
        if key is not None:
            byte ^= (key + pos - start) & 255
        pos += 1
        if byte != 0x90:
            size += 1
            previous = True
            continue
        if pos == end:
            return size, False
        repeat = data[pos]
        if key is not None:
            repeat ^= (key + pos - start) & 255
        pos += 1
        if repeat == 0:
            size += 1
            previous = True
        elif not previous:
            return size, False
        else:
            size += repeat - 1
    return size, True


def _vault_issue(data):
    if len(data) < 16:
        return None   # the adapter handles truncated headers
    declared = struct.unpack_from("<H", data, 4)[0]
    index_offset = struct.unpack_from("<I", data, 8)[0]
    if not 16 <= index_offset <= len(data):
        return None   # the adapter stops at this invalid index
    count = min(declared, (len(data) - index_offset) // 16)
    index_end = index_offset + count * 16
    output = count * VAULT_ENTRY_OUTPUT_CHARGE
    if output > MAX_VAULT_OUTPUT_BYTES:
        return "VAULT projected output exceeds the %d-byte safety budget" % MAX_VAULT_OUTPUT_BYTES

    work = 0
    for i in range(count):
        base = index_offset + i * 16
        flags = data[base + 3]
        offset = struct.unpack_from("<I", data, base + 8)[0]
        stored = struct.unpack_from("<H", data, base + 12)[0]
        end = offset + stored
        # The decoder does not expand invalid blocks. Avoid using their hostile
        # length/offset declarations in projections or iterating their ranges.
        if (stored < 4 or offset < 16 or end > len(data)
                or (offset < index_end and end > index_offset)):
            continue
        if (data[offset:offset + 2] != b"BL" or
                struct.unpack_from("<H", data, offset + 2)[0] != struct.unpack_from("<H", data, base)[0]):
            continue   # a mismatched block header is never expanded by the adapter
        payload = stored - 4
        text = data[base + 2] == 1
        if flags & 1:
            projections = [_vault_rle_projection(data, offset + 4, end,
                           data[6] if flags & 2 else None)]
            if flags & 2:
                projections.append(_vault_rle_projection(data, offset + 4, end))
            # Both orderings may be constructed, even when the first matches.
            # Eight conservative byte-passes cover RLE temporaries/copies, XOR,
            # hashing, plausibility and UTF-8 failure plus fallback per candidate;
            # the stored-byte charge also covers the allocation-free scans.
            work += 8 * sum(size for size, _ in projections) + (4 if flags & 2 else 2) * payload
            expanded = max((size for size, valid in projections if valid), default=0)
        else:
            # Plain binary retains a digest, not the selected payload. Text adds
            # plausibility, UTF-8 and possible fallback passes; XOR adds a pass.
            work += ((5 if text else 2) + int(bool(flags & 2))) * payload
            expanded = payload
        # Bitmap/binary output retains fixed metadata and hashes, not decoded
        # bytes. Text alone needs a worst-width Unicode payload allowance.
        if text:
            output += 4 * expanded
        if work > MAX_VAULT_WORK_BYTES:
            return "VAULT projected payload work exceeds the %d-byte safety budget" % MAX_VAULT_WORK_BYTES
        if output > MAX_VAULT_OUTPUT_BYTES:
            return "VAULT projected output exceeds the %d-byte safety budget" % MAX_VAULT_OUTPUT_BYTES
    return None


def resource_issue(data: bytes, fmt: str):
    """Return an explicit refusal reason, or None when preflight permits work.

    PAK/WAD and document adapters enforce their own entry/text/hash budgets;
    UNKNOWN analysis is independently prefix-bounded by the engine. This helper
    only guards the M1/M2 adapters without changing their owned implementations.
    """
    if fmt not in LEGACY_FORMATS:
        return None
    if fmt == "VAULT":
        # Entry-count, exact expansion, repeated work and retained output replace
        # this format's coarse input ceiling. The engine's 128 MiB cap remains.
        return _vault_issue(data)
    if len(data) > MAX_LEGACY_INPUT_BYTES:
        return "%s input exceeds the %d-byte legacy decoder safety limit" % (fmt, MAX_LEGACY_INPUT_BYTES)
    minimum = MIN_ITEM_BYTES.get(fmt)
    if minimum is not None and len(data) > minimum * MAX_STRUCTURAL_ITEMS:
        return ("%s conservative structural-item projection exceeds the %d-item safety budget"
                % (fmt, MAX_STRUCTURAL_ITEMS))
    return None
