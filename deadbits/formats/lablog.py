"""LABLOG: benchtop analytical-instrument data logger (early 1990s).

Layout (little-endian), derived from s05-s07 and confirmed on s05 (expected_outputs); every block CRC
verified 7/7 on s05 and the header CRC on all three:

  header (32): "LLOG" | version u8 | nchan u8 | interval u16 (units of 10 ms) | instrument char[16]
               | start u32 (seconds since 1990-01-01 -- ASSUMPTION confirmed on s05) | declared_blocks u16
               | header_crc u16 (CRC-16/CCITT-FALSE over bytes 0..29)
  block      : B1 | type u8 | len u16 | payload[len] | crc u16 (CRC-16/CCITT-FALSE over type..payload)
    type 3 channel table: per channel unit char[4] + scale f32 + offset f32
    type 1 samples      : first_sample u16 | n u8 | n x nchan int16;  value = raw*scale + offset;
                          raw == -32768 is a dropout (null)
    type 2 event        : sample u16 | severity u8 | msg_len u8 | message
"""
import datetime
import math
import struct
from array import array

from ..model import Result, unverified
from ..util.checksums import crc16_ccitt_false

NAME = "LABLOG"
MAGIC = b"LLOG"
HEADER_LEN = 32
SYNC = 0xB1
EPOCH = datetime.datetime(1990, 1, 1)
DROPOUT = -32768


def _make_crc_tables():
    byte_table = []
    for byte in range(256):
        value = byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 65535 if value & 32768 else (value << 1) & 65535
        byte_table.append(value)
    # Each pair applies the linear CRC transformation for 2**power zero
    # bytes. Encoded blocks require at most 65538 bytes, hence 17 powers.
    low = [((value << 8) & 65535) ^ byte_table[value >> 8] for value in range(256)]
    high = [byte_table[value] for value in range(256)]
    shifts = []
    for _ in range(17):
        shifts.append((tuple(low), tuple(high)))
        low, high = ([low[value & 255] ^ high[value >> 8] for value in low],
                     [low[value & 255] ^ high[value >> 8] for value in high])
    return tuple(byte_table), tuple(shifts)


_CRC_BYTES, _CRC_SHIFTS = _make_crc_tables()


def _shift_crc(value, length):
    power = 0
    while length:
        if length & 1:
            low, high = _CRC_SHIFTS[power]
            value = low[value & 255] ^ high[value >> 8]
        length >>= 1
        power += 1
    return value


class _CRCIndex:
    """Exact interval CRCs after one lazy O(N) pass, using 2*(N+1) bytes.

    A zero-initialized prefix and the CRC's linear shift transformation give
    CRC(start:end, init) = prefix[end] ^ shift(prefix[start] ^ init, length).
    This prevents overlapping candidate blocks from repeatedly hashing bytes.
    """

    def __init__(self, data):
        self.data = data
        self.prefix = None

    @property
    def active(self):
        return self.prefix is not None

    def _build(self):
        prefix = array('H', [0])
        value = 0
        for byte in self.data:
            value = ((value << 8) & 65535) ^ _CRC_BYTES[(value >> 8) ^ byte]
            prefix.append(value)
        self.prefix = prefix

    def crc(self, start, end, init=65535):
        if self.prefix is None:
            self._build()
        return self.prefix[end] ^ _shift_crc(self.prefix[start] ^ init, end - start)


def detect(data: bytes) -> float:
    if data[:4] != MAGIC:
        return 0.0
    if len(data) >= HEADER_LEN and crc16_ccitt_false(data[:30]) == struct.unpack_from("<H", data, 30)[0]:
        return 1.0
    # A magic prefix alone also occurs in unrelated/truncated text. An intact
    # block or a coherent (possibly incomplete) header supplies separate proof.
    if len(data) >= 12 and data[4] == 1 and data[5] and struct.unpack_from("<H", data, 6)[0]:
        instrument = data[8:min(24, len(data))].split(b"\0")[0]
        if len(instrument) >= 4 and all(32 <= c < 127 for c in instrument):
            return 0.8
    scanner = _BlockScanner(data)
    p = scanner.next_valid(HEADER_LEN)
    while p is not None:
        typ, payload, end, _ = _block_at(data, p, scanner.crc_index)
        if ((typ == 3 and len(payload) > 0 and len(payload) % 12 == 0 and len(payload) <= 12 * 255) or
                (typ == 2 and len(payload) >= 4 and len(payload) == 4 + payload[3])):
            return 0.8
        p = scanner.next_valid(end)
    return 0.0


def _block_at(data: bytes, pos: int, crc_index=None, materialize=True):
    """-> (type, payload, end, crc_ok) if a structurally complete block starts at pos, else None."""
    if pos + 4 > len(data) or data[pos] != SYNC:
        return None
    ln = struct.unpack_from("<H", data, pos + 2)[0]
    end = pos + 4 + ln + 2
    if end > len(data):
        return None
    checksum = (crc_index.crc(pos + 1, pos + 4 + ln) if crc_index is not None else
                crc16_ccitt_false(memoryview(data)[pos + 1:pos + 4 + ln]))
    ok = checksum == struct.unpack_from("<H", data, pos + 4 + ln)[0]
    payload = data[pos + 4:pos + 4 + ln] if materialize else memoryview(data)[pos + 4:pos + 4 + ln]
    return data[pos + 1], payload, end, ok


class _BlockScanner:
    """Forward CRC-valid lookahead with constant cache space.

    Decode positions only advance. Keeping the next valid marker (or the fact
    that EOF was searched) prevents rescanning a suffix for every damaged block.
    """

    def __init__(self, data, crc_index=None):
        self.data = data
        self.crc_index = crc_index if crc_index is not None else _CRCIndex(data)
        self.cursor = HEADER_LEN
        self.candidate = None
        self.exhausted = False

    def next_valid(self, start):
        if self.candidate is not None and self.candidate >= start:
            return self.candidate
        if self.exhausted:
            return None
        p = self.data.find(bytes([SYNC]), max(start, self.cursor))
        while p != -1:
            self.cursor = p + 1
            blk = _block_at(self.data, p, self.crc_index, materialize=False)
            if blk and blk[3]:
                self.candidate = p
                return p
            p = self.data.find(bytes([SYNC]), self.cursor)
        self.exhausted = True
        self.candidate = None
        return None


def _repair_length(data, pos, nchan, original, crc_index=None):
    """Repair only a length whose original stored CRC proves the reconstruction.

    The known type supplies one candidate length; no payload byte, type, count,
    or checksum is changed. A CRC-valid original block always takes precedence.
    """
    if original is not None and original[3]:
        return None
    if pos + 4 > len(data) or data[pos] != SYNC:
        return None
    typ = data[pos + 1]
    if typ == 3:
        length = 12 * nchan
    elif typ == 1 and pos + 7 <= len(data):
        length = 3 + 2 * data[pos + 6] * nchan
    elif typ == 2 and pos + 8 <= len(data):
        length = 4 + data[pos + 7]
    else:
        return None
    if length > 65535 or length == struct.unpack_from("<H", data, pos + 2)[0]:
        return None
    end = pos + 4 + length + 2
    if end > len(data):
        return None
    index = crc_index if crc_index is not None else _CRCIndex(data)
    restored_header = crc16_ccitt_false(bytes([typ]) + struct.pack("<H", length))
    if index.crc(pos + 4, end - 2, restored_header) != struct.unpack_from("<H", data, end - 2)[0]:
        return None
    payload = data[pos + 4:end - 2]
    return typ, payload, end, True


def _inferred_channel_count(data, crc_index=None):
    """A unique count independently supported by intact table and sample blocks.

    At most 255 possible counts are retained. Conflicting corroborated counts
    make the result ambiguous and are never resolved using the damaged header.
    """
    tables, samples = set(), set()
    scanner = _BlockScanner(data, crc_index)
    p = scanner.next_valid(HEADER_LEN)
    while p is not None:
        typ, payload, end, _ = _block_at(data, p, scanner.crc_index)
        if typ == 3 and len(payload) and len(payload) % 12 == 0:
            count = len(payload) // 12
            if count <= 255 and all(math.isfinite(v) for c in range(count)
                                    for v in struct.unpack_from("<ff", payload, 12 * c + 4)):
                tables.add(count)
        elif typ == 1 and len(payload) >= 3 and payload[2]:
            width = 2 * payload[2]
            if (len(payload) - 3) % width == 0:
                count = (len(payload) - 3) // width
                if 1 <= count <= 255:
                    samples.add(count)
        # A valid enclosing block establishes its boundary. Do not mistake raw
        # payload bytes for independent table/sample corroboration.
        p = scanner.next_valid(end)
    candidates = tables & samples
    return next(iter(candidates)) if len(candidates) == 1 else None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res

    version, nchan, interval = data[4], data[5], struct.unpack_from("<H", data, 6)[0] * 10
    instrument = data[8:24].split(b"\0")[0].decode("latin-1")
    start = struct.unpack_from("<I", data, 24)[0]
    declared = struct.unpack_from("<H", data, 28)[0]
    try:
        start_iso = (EPOCH + datetime.timedelta(seconds=start)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OverflowError:
        start_iso = None
    res.metadata = {"version": version, "instrument": instrument, "sample_interval_ms": interval,
                    "channels": [], "start_time_utc": start_iso, "declared_block_count": declared, "events": []}
    header_ok = crc16_ccitt_false(data[:30]) == struct.unpack_from("<H", data, 30)[0]
    crc_index = _CRCIndex(data)
    if not header_ok:
        res.add_damage("header_checksum", 30, "header CRC-16 does not match; header fields unverified", False)
        inferred = _inferred_channel_count(data, crc_index)
        if inferred is not None and inferred != nchan:
            nchan = inferred
            res.damage[-1]["detail"] += "; channel count %d supported by CRC-valid table and samples" % inferred

    if nchan == 0:
        res.add_damage("invalid_value", 5, "zero channels; sample layout cannot be decoded", True)
        res.status = "failed"
        return res

    scale = offset = units = None
    calibration_issues = ["invalid_value"]
    channel_tables = 0
    historical_channels = None
    unit_invalidated_prefix = 0
    blocks_seen = 0
    unverified_any = not header_ok
    truncated = False
    framing_lost = False
    pos = HEADER_LEN
    scanner = _BlockScanner(data, crc_index)
    while pos < size:
        blk = _block_at(data, pos, crc_index if crc_index.active else None, materialize=False)
        repaired = _repair_length(data, pos, nchan, blk, crc_index)
        if repaired is not None:
            blk = repaired
            res.add_damage("bad_length", pos + 2, "block length restored to %d bytes using its stored CRC"
                           % len(blk[1]), False)
        if blk is None:
            # not at a block start (garbage) or block cut off by EOF
            framing_lost = True
            calibration_issues = sorted(set(calibration_issues + ["bad_length"]))
            if data[pos] == SYNC and (pos + 4 > size or
                    pos + 4 + struct.unpack_from("<H", data, pos + 2)[0] + 2 > size):
                # a plausible block header whose body runs past EOF -> truncated, unless a later valid block exists
                later = scanner.next_valid(pos + 1)
                if later is None:
                    res.add_damage("truncated", pos, "file ends inside a block", True)
                    truncated = True
                    break
                res.add_damage("bad_length", pos + 2, "block length overruns later CRC-valid block at %d" % later, True)
                pos = later
                continue
            later = scanner.next_valid(pos + 1)
            end = later if later is not None else size
            res.add_damage("unparsed_bytes", pos, "%d bytes that are not a valid block" % (end - pos), True)
            unverified_any = True
            pos = end
            continue
        typ, payload, end, crc_ok = blk
        if not crc_ok:
            # resynchronise on a later block with a valid CRC, otherwise accept this block as unverified
            later = scanner.next_valid(pos + 1)
            shape_ok = ((typ == 3 and len(payload) == 12 * nchan) or
                        (typ == 1 and len(payload) >= 3 and len(payload) == 3 + 2 * payload[2] * nchan) or
                        (typ == 2 and len(payload) >= 4 and len(payload) == 4 + payload[3]))
            if later is not None and (later < end or not shape_ok):
                res.add_damage("bad_length", pos + 2, "damaged block framing; resynchronised at CRC-valid block %d"
                               % later, True)
                framing_lost = True
                calibration_issues = sorted(set(calibration_issues + ["bad_length"]))
                unverified_any = True
                pos = later
                continue
            res.add_damage("crc_mismatch", pos, "block type %d CRC mismatch; samples unverified" % typ, True)
            unverified_any = True
        # A failed candidate may overlap the next selected block. Materialize
        # only after choosing this block, so rejected overlapping payloads stay
        # zero-copy as well as avoiding repeated CRC work.
        payload = bytes(payload)
        blocks_seen += 1
        issues = [] if crc_ok else ["crc_mismatch"]
        if not header_ok:
            issues.append("header_checksum")   # time_ms derives from the (unverified) sample interval
        if typ == 3:
            channel_tables += 1
            if channel_tables > 1:
                res.add_damage("invalid_value", pos, "repeated channel table; later samples use this table", False)
            # A malformed replacement must not leave the previous calibration trusted.
            scale = offset = units = None
            # Keep the last known unit list for historical samples even if a
            # replacement is malformed; clearing calibration still prevents its
            # use for following samples.
            calibration_issues = [] if crc_ok else ["crc_mismatch"]
            if len(payload) == 12 * nchan:
                units, scale, offset = [], [], []
                for c in range(nchan):
                    u, sc, of = struct.unpack_from("<4sff", payload, 12 * c)
                    units.append(u.split(b"\0")[0].decode("latin-1"))
                    scale.append(sc)
                    offset.append(of)
                channels = [{"index": i, "unit": u} for i, u in enumerate(units)]
                if historical_channels and historical_channels != channels:
                    # The contract has one channel list, so historical units are
                    # ambiguous when a later table changes them.
                    for index in range(unit_invalidated_prefix, len(res.records)):
                        unverified(res.records[index], "invalid_value")
                    unit_invalidated_prefix = len(res.records)
                historical_channels = channels
                res.metadata["channels"] = channels
                if not all(math.isfinite(v) for v in scale + offset):
                    calibration_issues.append("invalid_value")
                    res.add_damage("invalid_value", pos, "channel calibration contains non-finite values", True)
            else:
                calibration_issues.append("bad_length")
                res.add_damage("bad_length", pos, "channel table is %d bytes, expected %d" % (len(payload), 12 * nchan), True)
                unverified_any = True
        elif typ == 1:
            if len(payload) >= 3:
                first, n = struct.unpack_from("<HB", payload, 0)
            else:
                first = n = 0
            if len(payload) != 3 + 2 * n * nchan:
                res.add_damage("bad_length", pos, "sample block length %d inconsistent with %d samples x %d channels"
                               % (len(payload), n, nchan), True)
                unverified_any = True
            else:
                raws = struct.unpack_from("<%dh" % (n * nchan), payload, 3)
                for i in range(n):
                    row = raws[i * nchan:(i + 1) * nchan]
                    if scale is None:
                        vals = [None] * nchan
                        rec_issues = issues + calibration_issues
                    else:
                        vals = [None if r == DROPOUT or not (math.isfinite(scale[c]) and math.isfinite(offset[c]))
                                else round(r * scale[c] + offset[c], 6) for c, r in enumerate(row)]
                        rec_issues = issues + calibration_issues
                    rec = {"sample": first + i, "time_ms": (first + i) * interval, "values": vals}
                    if rec_issues:
                        unverified(rec, *rec_issues)
                    res.records.append(rec)
                if scale is None:
                    res.add_damage("invalid_value", pos, "no usable channel calibration before samples; calibrated values unavailable", True)
        elif typ == 2:
            if len(payload) >= 4 and len(payload) == 4 + payload[3]:
                sample, sev = struct.unpack_from("<HB", payload, 0)
                event = {"sample": sample, "severity": sev, "message": payload[4:].decode("latin-1")}
                if issues:
                    unverified(event, *issues)
                res.metadata["events"].append(event)
            else:
                res.add_damage("bad_length", pos, "event block malformed", True)
                unverified_any = True
        else:
            if not crc_ok:
                calibration_issues = sorted(set(calibration_issues + ["crc_mismatch"]))
            res.add_damage("unknown_record", pos, "unknown block type %d (%d bytes skipped)" % (typ, len(payload)), False)
        pos = end

    if not truncated and not framing_lost and declared != blocks_seen:
        res.add_damage("count_mismatch", 28, "header declares %d blocks, %d found" % (declared, blocks_seen),
                       blocks_seen < declared)
    res.records.sort(key=lambda r: r["sample"])
    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
