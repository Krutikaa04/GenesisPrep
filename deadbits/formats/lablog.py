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

from ..model import Result, unverified
from ..util.checksums import crc16_ccitt_false

NAME = "LABLOG"
MAGIC = b"LLOG"
HEADER_LEN = 32
SYNC = 0xB1
EPOCH = datetime.datetime(1990, 1, 1)
DROPOUT = -32768


def detect(data: bytes) -> float:
    if data[:4] != MAGIC:
        return 0.0
    if len(data) >= HEADER_LEN and crc16_ccitt_false(data[:30]) == struct.unpack_from("<H", data, 30)[0]:
        return 1.0
    return 0.8


def _block_at(data: bytes, pos: int):
    """-> (type, payload, end, crc_ok) if a structurally complete block starts at pos, else None."""
    if pos + 4 > len(data) or data[pos] != SYNC:
        return None
    ln = struct.unpack_from("<H", data, pos + 2)[0]
    end = pos + 4 + ln + 2
    if end > len(data):
        return None
    ok = crc16_ccitt_false(data[pos + 1:pos + 4 + ln]) == struct.unpack_from("<H", data, pos + 4 + ln)[0]
    return data[pos + 1], data[pos + 4:pos + 4 + ln], end, ok


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
    if not header_ok:
        res.add_damage("header_checksum", 30, "header CRC-16 does not match; header fields unverified", False)

    if nchan == 0:
        res.add_damage("invalid_value", 5, "zero channels; sample layout cannot be decoded", True)
        res.status = "failed"
        return res

    scale = offset = units = None
    calibration_issues = ["invalid_value"]
    channel_tables = 0
    blocks_seen = 0
    unverified_any = not header_ok
    truncated = False
    framing_lost = False
    pos = HEADER_LEN
    while pos < size:
        blk = _block_at(data, pos)
        if blk is None:
            # not at a block start (garbage) or block cut off by EOF
            framing_lost = True
            calibration_issues = sorted(set(calibration_issues + ["bad_length"]))
            if data[pos] == SYNC and (pos + 4 > size or
                    pos + 4 + struct.unpack_from("<H", data, pos + 2)[0] + 2 > size):
                # a plausible block header whose body runs past EOF -> truncated, unless a later valid block exists
                later = _next_valid(data, pos + 1)
                if later is None:
                    res.add_damage("truncated", pos, "file ends inside a block", True)
                    truncated = True
                    break
                res.add_damage("bad_length", pos + 2, "block length overruns later CRC-valid block at %d" % later, True)
                pos = later
                continue
            later = _next_valid(data, pos + 1)
            end = later if later is not None else size
            res.add_damage("unparsed_bytes", pos, "%d bytes that are not a valid block" % (end - pos), True)
            unverified_any = True
            pos = end
            continue
        typ, payload, end, crc_ok = blk
        if not crc_ok:
            # resynchronise on a later block with a valid CRC, otherwise accept this block as unverified
            later = _next_valid(data, pos + 1)
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
            previous_channels = res.metadata["channels"]
            res.metadata["channels"] = []
            calibration_issues = [] if crc_ok else ["crc_mismatch"]
            if len(payload) == 12 * nchan:
                units, scale, offset = [], [], []
                for c in range(nchan):
                    u, sc, of = struct.unpack_from("<4sff", payload, 12 * c)
                    units.append(u.split(b"\0")[0].decode("latin-1"))
                    scale.append(sc)
                    offset.append(of)
                channels = [{"index": i, "unit": u} for i, u in enumerate(units)]
                if previous_channels and previous_channels != channels:
                    # The contract has one channel list, so historical units are
                    # ambiguous when a later table changes them.
                    for record in res.records:
                        unverified(record, "invalid_value")
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


def _next_valid(data: bytes, start: int):
    """Position of the next block that is structurally complete AND has a valid CRC, or None."""
    p = data.find(bytes([SYNC]), start)
    while p != -1:
        b = _block_at(data, p)
        if b and b[3]:
            return p
        p = data.find(bytes([SYNC]), p + 1)
    return None
