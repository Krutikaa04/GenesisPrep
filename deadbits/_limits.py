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
RLE_EXPANSION_FACTOR = 127
LEGACY_FORMATS = frozenset(("LIBRA-98", "LABLOG", "EBCDIC-DUMP", "VAULT", "WKS", "CVT"))

# These minimum byte costs include hostile records, not just successful data.
# WKS may emit damage for each four-byte unknown opcode, EBCDIC for each
# five-byte unknown RDW, and LABLOG may emit one sample per two payload bytes.
MIN_ITEM_BYTES = {"WKS": 4, "EBCDIC-DUMP": 5, "LABLOG": 2}


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
        payload = stored - 4
        expanded = payload * (RLE_EXPANSION_FACTOR if flags & 1 else 1)
        # With both flags, the decoder can construct both XOR/RLE orderings.
        # The allowance covers those candidates, XOR iterations, hashing and
        # text conversion. Aliases are charged separately: the decoder does
        # not cache them. Index size is u16 and is intentionally NOT a bound.
        work += 6 * expanded + 2 * payload
        output += 4 * expanded   # worst-width Unicode text from a kept payload
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
    if len(data) > MAX_LEGACY_INPUT_BYTES:
        return "%s input exceeds the %d-byte legacy decoder safety limit" % (fmt, MAX_LEGACY_INPUT_BYTES)
    minimum = MIN_ITEM_BYTES.get(fmt)
    if minimum is not None and len(data) > minimum * MAX_STRUCTURAL_ITEMS:
        return ("%s conservative structural-item projection exceeds the %d-item safety budget"
                % (fmt, MAX_STRUCTURAL_ITEMS))
    return _vault_issue(data) if fmt == "VAULT" else None
