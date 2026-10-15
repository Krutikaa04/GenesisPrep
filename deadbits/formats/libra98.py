"""LIBRA-98: municipal library circulation database (~1998).

Layout (little-endian), derived from s01-s04 and confirmed on s01-s03 (checksums) and s01/s04
(expected_outputs):

  header : "LB98" | version u8 | flags u8 (bit0 -> cp1252, else cp437) | count u16
           | created: DOS date u16 + DOS time u16 | data_offset u16 | branch_id u16
           [extra header bytes up to data_offset, e.g. a vendor string]
  record : A5 | len u8 | flags u8 | id u32 | title pascal | author pascal | year-1500 u16
           | price_cents u16 | copies u8 | isbn char[10] | due_date DOS u16 (0 = none) | chk u8
           len counts flags..chk;  chk = sum8(flags .. byte before chk)
           flags: bit0 checked_out, bit1 deleted, bit2 reference_only   (bits 1-2: ASSUMPTION)
  trailer: "END!" | sum16 of every byte before "END!" (u16)
"""
import struct

from ..model import Result, unverified
from ..util import dosdate

NAME = "LIBRA-98"
MAGIC = b"LB98"
HEADER_LEN = 16
MARKER = 0xA5
RECORD_MIN = 1 + 4 + 1 + 1 + 2 + 2 + 1 + 10 + 2 + 1   # flags,id,tlen,alen,year,price,copies,isbn,due,chk


def detect(data: bytes) -> float:
    if data[:4] != MAGIC:
        return 0.0
    if len(data) >= HEADER_LEN:
        off = struct.unpack_from("<H", data, 12)[0]
        if HEADER_LEN <= off <= len(data):
            return 1.0
    return 0.7   # magic present but header short/damaged: still LIBRA-98, handled as damage


def _parse_record(data: bytes, pos: int, enc: str):
    """-> (record, end, issues) for a complete record at pos (marker already checked)."""
    ln = data[pos + 1]
    end = pos + 2 + ln
    body = data[pos + 2:end]
    issues = []
    rec = {}
    try:
        if ln < RECORD_MIN:
            raise IndexError("record shorter than minimum")
        flags = body[0]
        rid = struct.unpack_from("<I", body, 1)[0]
        p = 5
        tl = body[p]; p += 1
        title = body[p:p + tl]; p += tl
        al = body[p]; p += 1
        author = body[p:p + al]; p += al
        if p + 2 + 2 + 1 + 10 + 2 + 1 != len(body):
            raise IndexError("field lengths do not add up to record length")
        year, price = struct.unpack_from("<HH", body, p); p += 4
        copies = body[p]; p += 1
        isbn = body[p:p + 10]; p += 10
        due = struct.unpack_from("<H", body, p)[0]; p += 2
        chk = body[p]
        due_iso = None
        if due:
            due_iso = dosdate.iso_date(due)
            if due_iso is None:
                issues.append("invalid_value")
        if not all(c in b"0123456789X" for c in isbn):
            issues.append("invalid_value")
        try:
            title.decode(enc)
            author.decode(enc)
        except UnicodeDecodeError:
            issues.append("invalid_value")
        if sum(body[:-1]) & 0xFF != chk:
            issues.append("checksum_mismatch")
        rec = {
            "id": rid,
            "title": title.decode(enc, "replace"),
            "author": author.decode(enc, "replace"),
            "year": year + 1500,
            "price_cents": price,
            "copies": copies,
            "isbn": isbn.decode("ascii", "replace"),
            "checked_out": bool(flags & 1),
            "deleted": bool(flags & 2),
            "reference_only": bool(flags & 4),
            "due_date": due_iso,
        }
    except (IndexError, struct.error):
        issues.append("bad_length")
    return rec, end, sorted(set(issues))


def _parse_by_fields(data: bytes, pos: int, enc: str):
    """Recover a record whose length byte is wrong: the fields delimit themselves and the checksum
    still verifies them. -> (record, end) or None. Requires a matching checksum and sane ISBN."""
    size = len(data)
    try:
        flags = data[pos + 2]
        rid = struct.unpack_from("<I", data, pos + 3)[0]
        p = pos + 7
        tl = data[p]; p += 1
        title = data[p:p + tl]; p += tl
        al = data[p]; p += 1
        author = data[p:p + al]; p += al
        year, price = struct.unpack_from("<HH", data, p); p += 4
        copies = data[p]; p += 1
        isbn = data[p:p + 10]; p += 10
        due = struct.unpack_from("<H", data, p)[0]; p += 2
        chk = data[p]; p += 1
        title_text, author_text = title.decode(enc), author.decode(enc)
    except (IndexError, struct.error, UnicodeDecodeError):
        return None
    if p - pos - 2 > 255 or p > size or sum(data[pos + 2:p - 1]) & 0xFF != chk or len(isbn) != 10:
        return None
    if not all(c in b"0123456789X" for c in isbn):
        return None
    due_iso = dosdate.iso_date(due) if due else None
    if due and due_iso is None:
        return None
    return ({"id": rid, "title": title_text, "author": author_text,
             "year": year + 1500, "price_cents": price, "copies": copies,
             "isbn": isbn.decode("ascii"), "checked_out": bool(flags & 1), "deleted": bool(flags & 2),
             "reference_only": bool(flags & 4), "due_date": due_iso}, p)


def _valid_chain(data: bytes, start: int, stop: int, count: int, enc: str) -> bool:
    """Corroborate an offset with exactly count intact records ending at the trailer."""
    pos = start
    for _ in range(count):
        if pos + 2 > stop or data[pos] != MARKER or pos + 2 + data[pos + 1] > stop:
            return False
        rec, end, issues = _parse_record(data, pos, enc)
        if not rec or issues:
            return False
        pos = end
    return pos == stop


def _recover_data_offset(data: bytes, declared: int, count: int, enc: str):
    """Repair only a uniquely corroborated pointer, not arbitrary vendor-header bytes.

    Each candidate must explain the declared count, every record checksum, and
    the final file checksum after correcting ONLY the pointer. A complete valid
    declared chain, an intact file, a compound checksum failure, or competing
    valid chains does not authorize guessing another start. The two-byte
    pointer admits at most 256 candidates.
    """
    if declared <= HEADER_LEN or not count or data[-6:-2] != b"END!":
        return None
    stop = len(data) - 6
    # A damaged trailer must not make record-like vendor bytes replace an
    # already complete, count-valid chain at the declared start. Additive
    # checksum coincidences cannot overturn that independent framing evidence.
    if _valid_chain(data, declared, stop, count, enc):
        return None
    actual = sum(memoryview(data)[:stop]) & 0xFFFF
    stored = int.from_bytes(data[-2:], "little")
    if actual == stored:
        return None
    candidate_byte_sum = (stored - actual + data[12] + data[13]) & 0xFFFF
    if candidate_byte_sum > 510:
        return None
    recovered = None
    for high in range(256):
        low = candidate_byte_sum - high
        if not 0 <= low <= 255:
            continue
        candidate = (high << 8) | low
        if (HEADER_LEN <= candidate < min(declared, stop) and data[candidate] == MARKER
                and _valid_chain(data, candidate, stop, count, enc)):
            if recovered is not None:
                return None
            recovered = candidate
    return recovered


def _trailer_matches(data: bytes, pos: int, prefix_sum: int) -> bool:
    return (data[pos:pos + 4] == b"END!" and pos + 6 <= len(data)
            and prefix_sum & 0xFFFF == int.from_bytes(data[pos + 4:pos + 6], "little"))


def _resync(data: bytes, start: int, enc: str, prefix_sum: int):
    """Seek validated records or a trailer; a stray END! must not hide later records."""
    size = len(data)
    nxt = start
    trailer_candidate = None
    while nxt < size:
        if data[nxt:nxt + 4] == b"END!":
            if nxt + 6 > size or _trailer_matches(data, nxt, prefix_sum):
                return nxt, prefix_sum
            if trailer_candidate is None:
                trailer_candidate = nxt, prefix_sum
        if data[nxt] == MARKER and nxt + 2 <= size:
            if nxt + 2 + data[nxt + 1] <= size:
                rec, _, issues = _parse_record(data, nxt, enc)
                if rec and not issues:
                    return nxt, prefix_sum
            if _parse_by_fields(data, nxt, enc):
                return nxt, prefix_sum
        prefix_sum = (prefix_sum + data[nxt]) & 0xFFFF
        nxt += 1
    return trailer_candidate if trailer_candidate is not None else (size, prefix_sum)


def _partial_record(data: bytes, pos: int):
    """A record cut off by end-of-file: keep only fields that were fully read (never invent)."""
    avail = data[pos + 2:]
    if len(avail) >= 5:
        return {"id": struct.unpack_from("<I", avail, 1)[0]}
    return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res

    version, flags, count = data[4], data[5], struct.unpack_from("<H", data, 6)[0]
    date_w, time_w, data_off, branch = struct.unpack_from("<HHHH", data, 8)
    enc = "cp1252" if flags & 1 else "cp437"
    res.metadata = {
        "version": version,
        "encoding": enc,
        "created": dosdate.iso_datetime(date_w, time_w),
        "branch_id": branch,
        "declared_record_count": count,
        "data_offset": data_off,
    }
    if res.metadata["created"] is None:
        res.add_damage("invalid_value", 8, "created date/time is not a valid DOS timestamp", False)
    pos = data_off
    if not (HEADER_LEN <= data_off <= size):
        res.add_damage("oob_pointer", 12, "data_offset %d outside file (size %d); using %d" %
                       (data_off, size, HEADER_LEN), True)
        pos = HEADER_LEN
    elif version == 2:
        recovered = _recover_data_offset(data, data_off, count, enc)
        if recovered is not None:
            res.add_damage("invalid_value", 12,
                           "data_offset %d conflicts with the record chain; %d uniquely restores "
                           "record count and file checksum" % (data_off, recovered), False)
            pos = recovered

    # Carry the checksum alongside the scan. Restarting sum(data[:pos]) for
    # every resynchronisation made repeated local damage quadratic in file size.
    view = memoryview(data)
    prefix_sum = sum(view[:pos]) & 0xFFFF

    unknown_version = version != 2
    if unknown_version:
        res.add_damage("unknown_record", 4, "version %d is not confirmed; known record layout attempted" % version, False)
    unverified_any = unknown_version
    truncated = False
    trailer_seen = False
    header_integrity = False
    while pos < size:
        if size - pos < 4 and b"END!".startswith(data[pos:]):
            res.add_damage("truncated", pos, "file ends inside the trailer marker", False)
            truncated = True
            break
        if data[pos:pos + 4] == b"END!":
            checksum_ok = _trailer_matches(data, pos, prefix_sum)
            if not checksum_ok:
                later, later_sum = _resync(data, pos + 1, enc, (prefix_sum + data[pos]) & 0xFFFF)
                if later < size and (data[later] == MARKER or _trailer_matches(data, later, later_sum)):
                    res.add_damage("unparsed_bytes", pos,
                                   "%d unparsed bytes before a later validated record/trailer" % (later - pos), True)
                    pos, prefix_sum = later, later_sum
                    continue
            trailer_seen = True
            break
        if data[pos] != MARKER:
            # garbage between records: resync on the next record that validates, or END!
            end, end_sum = _resync(data, pos + 1, enc, (prefix_sum + data[pos]) & 0xFFFF)
            res.add_damage("unparsed_bytes", pos, "%d unparsed bytes between records" % (end - pos), True)
            unverified_any = True
            pos, prefix_sum = end, end_sum
            continue
        if pos + 2 > size or pos + 2 + data[pos + 1] > size:
            # The length byte is outside the record checksum. Try field-delimited
            # recovery before treating an exaggerated length as a real EOF cut.
            alt = _parse_by_fields(data, pos, enc)
            if alt:
                res.records.append(alt[0])
                res.add_damage("bad_length", pos + 1, "record length exceeds file; fields and checksum recovered", False)
                prefix_sum = (prefix_sum + sum(view[pos:alt[1]])) & 0xFFFF
                pos = alt[1]
                continue
            later, later_sum = _resync(data, pos + 1, enc, (prefix_sum + data[pos]) & 0xFFFF)
            if later < size:
                res.add_damage("bad_length", pos + 1, "record length exceeds file; resynchronised at %d" % later, True)
                pos, prefix_sum = later, later_sum
                continue
            truncated = True
            part = _partial_record(data, pos)
            if part:
                res.records.append(unverified(part, "truncated"))
            res.add_damage("truncated", pos, "file ends inside a record (needs %d bytes, %d present)" %
                           (2 + (data[pos + 1] if pos + 1 < size else 0), size - pos), True)
            pos = size
            break
        rec, end, issues = _parse_record(data, pos, enc)
        if not rec:
            alt = _parse_by_fields(data, pos, enc)
            if alt:
                # length byte is wrong but the fields + checksum verify: keep the record, report the defect
                res.records.append(alt[0])
                res.add_damage("bad_length", pos + 1, "record length byte %d is wrong (fields end at %d); "
                               "record recovered and checksum verified" % (data[pos + 1], alt[1] - pos - 2), False)
                unverified_any = True
                prefix_sum = (prefix_sum + sum(view[pos:alt[1]])) & 0xFFFF
                pos = alt[1]
                continue
            # fields do not fit the declared length, so the length cannot be trusted: rescan from the next byte
            nxt, next_sum = _resync(data, pos + 1, enc, (prefix_sum + data[pos]) & 0xFFFF)
            res.add_damage("bad_length", pos, "record length %d inconsistent with its fields; %d bytes skipped "
                           "until the next valid record" % (data[pos + 1], nxt - pos), True)
            unverified_any = True
            pos, prefix_sum = nxt, next_sum
            continue
        if rec:
            if issues:
                unverified(rec, *issues)
                unverified_any = True
            res.records.append(rec)
        for kind in issues:
            res.add_damage(kind, pos, {"bad_length": "record length inconsistent with its fields",
                                       "checksum_mismatch": "record checksum does not match",
                                       "invalid_value": "invalid text, ISBN or due date"}[kind], not rec or kind == "checksum_mismatch")
        prefix_sum = (prefix_sum + sum(view[pos:end])) & 0xFFFF
        pos = end

    if trailer_seen:
        stored_pos = pos + 4
        if stored_pos + 2 > size:
            res.add_damage("truncated", pos, "file ends inside the trailer", False)
            truncated = True
        else:
            stored = struct.unpack_from("<H", data, stored_pos)[0]
            header_integrity = prefix_sum == stored
            if not header_integrity:
                res.add_damage("checksum_mismatch", pos, "file checksum in trailer does not match", False)
                unverified_any = True
            if stored_pos + 2 < size:
                res.add_damage("unparsed_bytes", stored_pos + 2, "%d bytes after trailer" % (size - stored_pos - 2), False)
    elif not truncated:
        truncated = True
        res.add_damage("truncated", size, "END! trailer missing", True)

    found_n = len([r for r in res.records if "issues" not in r or "truncated" not in r["issues"]])
    if not truncated and count != found_n:
        res.add_damage("count_mismatch", 6, "header declares %d records, %d found" % (count, found_n),
                       found_n < count)

    # Preserve duplicate records rather than silently overwriting keyed data.
    by_id = {}
    for rec in res.records:
        by_id.setdefault(rec["id"], []).append(rec)
        if unknown_version:
            unverified(rec, "unknown_record")
        # Record checksums cover raw bytes, not the header's code-page choice.
        # A trailer-only error and a flipped codec flag are indistinguishable.
        # ASCII has the same meaning under both supported codecs.
        if not header_integrity and any(not rec.get(field, "").isascii() for field in ("title", "author")):
            unverified(rec, "truncated" if truncated else "checksum_mismatch")
    for rid, records in by_id.items():
        if len(records) > 1:
            res.add_damage("invalid_value", data_off if data_off <= size else HEADER_LEN,
                           "duplicate record id %d (%d occurrences retained)" % (rid, len(records)), False)
            for rec in records:
                unverified(rec, "invalid_value")
    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
