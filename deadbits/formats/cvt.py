"""CVT: Commodore 64 GEOS "convert" container (disk-image conversion).

Layout, derived from s18-s19 and confirmed on s18 (expected_outputs). All blocks are 254 bytes:

  block 0 (directory entry): type u8 | track,sector u16 | name char[16] (PETSCII, 0xA0 padded) | info t/s u16
        | structure u8 (0 seq, 1 vlir) | geos_type u8 | year-1900 u8, month, day, hour, minute | blocks u16 LE
        | "PRG formatted GEOS file V1.0" signature at 0x1E
  block 1 (info): class_name char[20] | author char[20] | description (NUL-terminated)
  SEQ  : blocks 2.. are the data; text = PETSCII decode with trailing NULs removed
  VLIR : block 2 = record index, 127 x (blocks u8, used-bytes-in-last-block u8); (0, 0xFF) = no record;
         record data follows, in index order, 254-byte blocks
`declared_blocks` counts the info block + (index block) + data blocks, i.e. every block after block 0.
"""
from ..model import Result, unverified
from ..util import petscii

NAME = "CVT"
BLK = 254
SIG = b"formatted GEOS file V"


def detect(data: bytes) -> float:
    if len(data) >= 0x22 + len(SIG) and data[0x22:0x22 + len(SIG)] == SIG:
        return 1.0
    return 0.0


def _modified(b: bytes):
    y, mo, d, h, mi = b[0], b[1], b[2], b[3], b[4]
    if 1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60:
        return "%04d-%02d-%02dT%02d:%02d" % (1900 + y, mo, d, h, mi)
    return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < BLK:
        res.status = "failed"
        res.add_damage("truncated", size, "directory block truncated: %d of %d bytes" % (size, BLK), True)
        return res
    structure = "vlir" if data[0x15] == 1 else "seq"
    declared = int.from_bytes(data[0x1C:0x1E], "little")
    modified = _modified(data[0x17:0x1C])
    res.metadata = {
        "name": petscii.decode_field(data[3:19]),
        "structure": structure,
        "geos_type": data[0x16],
        "modified": modified,
        "class_name": None, "author": None, "description": None,
        "declared_blocks": declared,
    }
    if data[0x15] not in (0, 1):
        res.add_damage("invalid_value", 0x15, "structure byte %d is neither seq (0) nor vlir (1)" % data[0x15], False)
    if modified is None:
        res.add_damage("invalid_value", 0x17, "modification timestamp is not a valid date", False)

    have_blocks = (size - BLK + BLK - 1) // BLK          # blocks present after block 0 (last may be partial)
    if size >= 2 * BLK:
        info = data[BLK:2 * BLK]
        res.metadata["class_name"] = petscii.decode_field(info[0:20])
        res.metadata["author"] = petscii.decode_field(info[20:40])
        res.metadata["description"] = petscii.decode_field(info[40:])
    else:
        res.add_damage("index_missing", BLK, "info block is missing or incomplete", True)

    body_start = 2 * BLK
    full = size >= (1 + declared) * BLK
    if size < (1 + declared) * BLK:
        res.add_damage("truncated", size, "file holds %d of %d declared blocks" %
                       (min(have_blocks, declared), declared), True)
    elif size > (1 + declared) * BLK:
        res.add_damage("unparsed_bytes", (1 + declared) * BLK, "%d bytes beyond the declared blocks" %
                       (size - (1 + declared) * BLK), False)

    end = min(size, (1 + declared) * BLK) if declared else size
    if structure == "seq":
        raw = data[body_start:end]
        text = petscii.decode(raw.rstrip(b"\0"))
        rec = {"slot": 0, "text": text}
        if not full:
            unverified(rec, "truncated")
        if size > body_start:
            res.records.append(rec)
    else:
        idx_end = body_start + BLK
        if size < idx_end:
            res.add_damage("index_missing", body_start, "VLIR record index block is missing or incomplete", True)
        else:
            index = data[body_start:idx_end]
            pos = idx_end
            used_blocks = 1  # the index block itself counts toward declared_blocks (after info)
            for slot in range(127):
                nb, last = index[2 * slot], index[2 * slot + 1]
                if nb == 0:
                    continue
                need = nb * BLK
                chunk = data[pos:pos + need]
                rec = {"slot": slot}
                if len(chunk) < need or last == 0 or last > BLK:
                    if last == 0 or last > BLK:
                        res.add_damage("bad_length", body_start + 2 * slot,
                                       "record %d last-block byte count %d is invalid" % (slot, last), True)
                    if len(chunk) < need:
                        res.add_damage("truncated", size, "record %d needs %d bytes, %d present" %
                                       (slot, need, len(chunk)), True)
                    raw = chunk
                    rec["text"] = petscii.decode(raw.rstrip(b"\0"))
                    res.records.append(unverified(rec, "truncated" if len(chunk) < need else "bad_length"))
                else:
                    raw = chunk[:need - BLK + last]
                    rec["text"] = petscii.decode(raw)
                    res.records.append(rec)
                pos += need
                used_blocks += nb
            if full and 1 + used_blocks != declared:
                res.add_damage("count_mismatch", 0x1C, "index accounts for %d blocks, header declares %d" %
                               (1 + used_blocks, declared), False)

    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or any(not r.get("verified", True) for r in res.records):
        res.status = "partial"
    return res
