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

Damage policy (M2):
  * VLIR: the index and the file size are independent evidence for the block count.  If the index total
    agrees with the file size but not with `declared_blocks`, the header field is the corrupted one: the
    records stay verified and only a lossless count_mismatch is reported.  If the index disagrees with both,
    record boundaries cannot be trusted: every record is flagged unverified + count_mismatch.
  * A slot with blocks == 0 but a byte count that is not 0 / 0xFF is a corrupted index entry (every later
    record would be mis-sliced): reported as invalid_value, records flagged unverified.
  * The last block of a VLIR record is NUL padded (assumption, true on s19): non-NUL bytes after the declared
    byte count, or a declared count that ends in padding, mean the count is corrupted -> unverified + bad_length.
  * Text containing PETSCII graphics (no text equivalent -> U+FFFD) is flagged unverified + invalid_value.
  * SEQ files larger than `declared_blocks` x 254 lose the excess: reported lossy, record unverified.
"""
from ..model import Result, unverified
from ..util import petscii

NAME = "CVT"
BLK = 254
SIG = b"formatted GEOS file V"
REPLACEMENT = "\ufffd"


def detect(data: bytes) -> float:
    if len(data) >= 0x22 + len(SIG) and data[0x22:0x22 + len(SIG)] == SIG:
        return 1.0
    return 0.0


def _modified(b: bytes):
    y, mo, d, h, mi = b[0], b[1], b[2], b[3], b[4]
    if 1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60:
        return "%04d-%02d-%02dT%02d:%02d" % (1900 + y, mo, d, h, mi)
    return None


def _flag_graphics(res: Result, rec: dict, offset: int) -> None:
    if REPLACEMENT in rec.get("text", ""):
        res.add_damage("invalid_value", offset, "record %d contains PETSCII graphics bytes with no text "
                       "equivalent" % rec["slot"], True)
        unverified(rec, "invalid_value")


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

    if size >= 2 * BLK:
        info = data[BLK:2 * BLK]
        res.metadata["class_name"] = petscii.decode_field(info[0:20])
        res.metadata["author"] = petscii.decode_field(info[20:40])
        res.metadata["description"] = petscii.decode_field(info[40:])
    else:
        res.add_damage("index_missing", BLK, "info block is missing or incomplete", True)

    body_start = 2 * BLK
    declared_end = (1 + declared) * BLK
    full = size >= declared_end
    file_total = size // BLK - 1 if size % BLK == 0 else None   # blocks after block 0, when the file is whole blocks

    def block_count_damage():
        if size < declared_end:
            have = (size + BLK - 1) // BLK - 1
            res.add_damage("truncated", size, "file holds %d of %d declared blocks" % (min(have, declared), declared), True)
        elif size > declared_end:
            res.add_damage("unparsed_bytes", declared_end, "%d bytes beyond the declared blocks" %
                           (size - declared_end), False)

    if structure == "seq":
        block_count_damage()
        end = min(size, declared_end) if declared else size
        raw = data[body_start:end]
        rec = {"slot": 0, "text": petscii.decode(raw.rstrip(b"\0"))}
        if not full:
            unverified(rec, "truncated")
        elif size > declared_end:
            res.damage[-1]["lossy"] = True      # excess data is dropped: it may be real content
            unverified(rec, "count_mismatch")
        _flag_graphics(res, rec, body_start)
        if size > body_start:
            res.records.append(rec)
    else:
        idx_end = body_start + BLK
        if size < idx_end:
            block_count_damage()
            res.add_damage("index_missing", body_start, "VLIR record index block is missing or incomplete", True)
        else:
            index = data[body_start:idx_end]
            pos = idx_end
            sum_blocks = 0
            index_suspect = False
            first_new = len(res.records)
            for slot in range(127):
                nb, last = index[2 * slot], index[2 * slot + 1]
                if nb == 0:
                    if last not in (0, 0xFF):
                        index_suspect = True
                        res.add_damage("invalid_value", body_start + 2 * slot,
                                       "index slot %d has 0 blocks but byte count %d (expected 0 or 255)" % (slot, last), True)
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
                    rec["text"] = petscii.decode(chunk.rstrip(b"\0"))
                    unverified(rec, "truncated" if len(chunk) < need else "bad_length")
                else:
                    used = need - BLK + last
                    rec["text"] = petscii.decode(chunk[:used])
                    if any(chunk[used:]):        # kit padding is NUL: data after the declared end = count too small
                        res.add_damage("bad_length", body_start + 2 * slot + 1,
                                       "record %d: non-padding bytes follow the declared last-block count %d" %
                                       (slot, last), True)
                        unverified(rec, "bad_length")
                    elif chunk[:used].endswith(b"\0"):   # declared end inside the padding = count too large
                        res.add_damage("bad_length", body_start + 2 * slot + 1,
                                       "record %d: declared last-block count %d includes NUL padding" %
                                       (slot, last), False)
                        rec["text"] = petscii.decode(chunk[:used].rstrip(b"\0"))
                        unverified(rec, "bad_length")
                _flag_graphics(res, rec, pos)
                res.records.append(rec)
                pos += need
                sum_blocks += nb
            index_total = 2 + sum_blocks          # info + index + data blocks
            if index_total == declared:
                block_count_damage()
            elif file_total is not None and file_total == index_total:
                res.add_damage("count_mismatch", 0x1C, "header declares %d blocks; the record index and the file "
                               "size both give %d" % (declared, index_total), False)
            else:
                res.add_damage("count_mismatch", 0x1C, "record index accounts for %d blocks, header declares %d, "
                               "file holds %d" % (index_total, declared, size // BLK - 1), True)
                index_suspect = True
            if index_suspect:
                for rec in res.records[first_new:]:
                    unverified(rec, "count_mismatch")

    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or any(not r.get("verified", True) for r in res.records):
        res.status = "partial"
    return res
