"""EBCDIC-DUMP: cp037 mainframe extracts with RDW or BDW/RDW framing.

H = type + title[20] + YYYYMMDD[8]; D = type + student_id[6] + name[20]
+ packed DOB[5] + packed GPA[3] + credits u16 BE + status[1]
+ packed balance[4] + filler[2]; T = type + packed count[4] + packed credits[5].
All descriptors include their four-byte header in their big-endian length.
Layouts are derived from s20-s22. There is no per-record checksum; structural
validation cannot detect plausible in-bounds content corruption.
"""
import datetime

from ..model import Result, unverified

NAME = "EBCDIC-DUMP"
H, D, T = 0xC8, 0xC4, 0xE3
D_LEN = 43
RECORD_LENGTHS = {H: 29, D: 44, T: 10}


def _packed(b: bytes):
    """Packed-decimal -> int; empty input or invalid digits/sign -> None."""
    if not b:
        return None
    value = 0
    for x in b[:-1]:
        hi, lo = x >> 4, x & 0xF
        if hi > 9 or lo > 9:
            return None
        value = value * 100 + hi * 10 + lo
    hi, sign = b[-1] >> 4, b[-1] & 0xF
    if hi > 9 or sign < 0xA:
        return None
    value = value * 10 + hi
    return -value if sign in (0xB, 0xD) else value


def _iso8(text: str):
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        return None
    try:
        return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
    except ValueError:
        return None


def _printable(raw: bytes) -> bool:
    """Allow printable cp037 text, including accented letters, but no controls."""
    return all(char.isprintable() for char in raw.decode('cp037'))


def _credible(rec: bytes) -> bool:
    """Stricter evidence for resynchronisation than a length/type byte alone."""
    if not rec or len(rec) != RECORD_LENGTHS.get(rec[0]):
        return False
    if rec[0] == H:
        return (_printable(rec[1:21]) and
                _iso8(rec[21:29].decode('cp037')) is not None)
    if rec[0] == T:
        return all(_packed(part) is not None and _packed(part) >= 0
                   for part in (rec[1:5], rec[5:10]))
    body = rec[1:]
    dob = _packed(body[26:31])
    return (all(0xf0 <= c <= 0xf9 for c in body[:6]) and
            _printable(body[6:26]) and _printable(body[36:37]) and
            dob is not None and 0 <= dob <= 99999999 and
            _iso8('%08d' % dob) is not None and
            _packed(body[31:34]) is not None and _packed(body[37:41]) is not None)


def _record_end(data: bytes, pos: int, end: int):
    """A complete known record descriptor, independent of field validity."""
    if pos + 5 > end or data[pos+2:pos+4] != b'\0\0':
        return None
    expected = RECORD_LENGTHS.get(data[pos+4])
    length = int.from_bytes(data[pos:pos+2], 'big')
    if expected is not None and length == expected + 4 and pos + length <= end:
        return pos + length
    return None


def _damaged_header_evidence(data: bytes, layout: str) -> bool:
    """Recognize a damaged H field only with two independently credible D records.

    Inspect at most eight coherently framed records; detection never copies or
    scans a whole suffix merely because a header field is malformed.
    """
    pos = 0 if layout == 'V' else 4
    if _record_end(data, pos, len(data)) != pos + 33 or data[pos+4] != H:
        return False
    block_end = len(data)
    if layout == 'VB':
        block_end = int.from_bytes(data[:2], 'big')
        if data[2:4] != b'\0\0' or not pos + 33 <= block_end <= len(data):
            return False
    students = 0
    for _ in range(8):
        if pos == block_end and layout == 'VB':
            if pos + 4 > len(data) or data[pos+2:pos+4] != b'\0\0':
                return False
            length = int.from_bytes(data[pos:pos+2], 'big')
            block_end = pos + length
            if length < 9 or block_end > len(data):
                return False
            pos += 4
        stop = _record_end(data, pos, block_end)
        if stop is None:
            return False
        if data[pos+4] == D and _credible(data[pos+4:stop]):
            students += 1
            if students == 2:
                return True
        pos = stop
    return False


def _layout(data: bytes):
    """Require a credible header or independently evidenced damaged-header framing."""
    for layout, off in (('V', 4), ('VB', 8)):
        if _credible(data[off:off + 29]) and data[off:off + 1] == bytes([H]):
            return layout
        # Short known-length header: retain conservative truncated recognition.
        prefix = data[off:off + 29]
        if (9 <= len(prefix) < 29 and prefix[0] == H and
                data[off-4:off] == b'\x00\x21\x00\x00' and
                _printable(prefix[1:])):
            return layout
        if _damaged_header_evidence(data, layout):
            return layout
    return None


def detect(data: bytes) -> float:
    layout = _layout(data)
    if layout is None:
        return 0.0
    off = 4 if layout == 'V' else 8
    ln = int.from_bytes(data[off-4:off-2], 'big')
    return 1.0 if ln == 33 and off + 29 <= len(data) else 0.7


def _next_record(data: bytes, start: int, end: int):
    """Seek only complete, schema-consistent known records inside the region."""
    for pos in range(start, max(start, end - 4)):
        stop = _record_end(data, pos, end)
        if stop is not None and _credible(data[pos+4:stop]):
            return pos
    return None


def _block_at(data: bytes, pos: int):
    """A complete BDW supported by record framing, not student field semantics.

    An invalid first RDW can also be bounded by the fixed schema and a following
    intact RDW, or an independently credible sole payload. All probes are bounded.
    """
    if pos + 9 > len(data) or data[pos+2:pos+4] != b'\0\0':
        return None
    length = int.from_bytes(data[pos:pos+2], 'big')
    end = pos + length
    if length < 9 or end > len(data):
        return None
    if _record_end(data, pos + 4, end) is not None:
        return end
    payload_length = RECORD_LENGTHS.get(data[pos+8], 0)
    stop = pos + 8 + payload_length
    if payload_length and stop <= end:
        if _record_end(data, stop, end) is not None:
            return end
        if stop == end and _credible(data[pos+8:stop]):
            return end
    return None


def _next_block(data: bytes, start: int):
    for pos in range(start, max(start, len(data) - 8)):
        if _block_at(data, pos) is not None:
            return pos
    return None


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, 'ok')
    size = len(data)
    layout = _layout(data) or 'V'
    trailer = None
    truncated = False
    framing_lost = False
    d_count = credits_sum = 0

    def consume(rec, pos, parent_issues):
        nonlocal trailer, d_count, credits_sum, framing_lost
        kind = rec[0]
        if kind == H:
            title_ok = _printable(rec[1:21])
            res.metadata['title'] = rec[1:21].decode('cp037').rstrip() if title_ok else None
            date = _iso8(rec[21:29].decode('cp037'))
            res.metadata['run_date'] = date
            if date is None:
                res.add_damage('invalid_value', pos, 'invalid header run date', False)
            if not title_ok:
                res.add_damage('invalid_value', pos, 'header title contains control characters', True)
        elif kind == D:
            body = rec[1:]
            issues = list(parent_issues)
            dob_n = _packed(body[26:31])
            dob = _iso8('%08d' % dob_n) if dob_n is not None and 0 <= dob_n <= 99999999 else None
            gpa_n, bal_n = _packed(body[31:34]), _packed(body[37:41])
            student_id = body[:6].decode('cp037')
            name_ok, status_ok = _printable(body[6:26]), _printable(body[36:37])
            if (dob is None or gpa_n is None or bal_n is None or
                    not student_id.isascii() or not student_id.isdigit() or
                    not name_ok or not status_ok):
                issues.append('invalid_value')
                res.add_damage('invalid_value', pos, 'record has invalid identifier/text/date/packed fields', True)
            credits = int.from_bytes(body[34:36], 'big')
            out = {'student_id': student_id, 'name': body[6:26].decode('cp037').rstrip() if name_ok else None,
                   'dob': dob, 'gpa': None if gpa_n is None else round(gpa_n / 100, 2),
                   'credits': credits, 'status': body[36:37].decode('cp037') if status_ok else None,
                   'balance': None if bal_n is None else round(bal_n / 100, 2)}
            if issues:
                unverified(out, *issues)
            res.records.append(out)
            d_count += 1
            credits_sum += credits
        elif kind == T:
            c, total = _packed(rec[1:5]), _packed(rec[5:10])
            if c is not None and total is not None and c >= 0 and total >= 0:
                trailer = c, total
                res.metadata['trailer_count'], res.metadata['trailer_credits_total'] = trailer
            else:
                res.add_damage('invalid_value', pos, 'trailer has invalid packed totals', False)
                framing_lost = True
        else:
            res.add_damage('unknown_record', pos, 'unknown record type 0x%02x (%d bytes skipped)' % (kind, len(rec)), False)
            framing_lost = True

    def read_region(start, end, parent_issues=(), already_truncated=False):
        nonlocal truncated, framing_lost
        pos = start
        while pos < end:
            if pos + 4 > end:
                if not already_truncated:
                    res.add_damage('truncated', pos, 'file/block ends inside a record descriptor', True)
                truncated = True
                break
            length = int.from_bytes(data[pos:pos+2], 'big')
            reserved_ok = data[pos+2:pos+4] == b'\0\0'
            stop = pos + length
            kind = data[pos+4] if pos + 4 < end else None
            schema_ok = kind not in RECORD_LENGTHS or length == 4 + RECORD_LENGTHS[kind]
            if length < 5 or not reserved_ok or stop > end or not schema_ok:
                later = _next_record(data, pos + 1, end)
                if later is not None:
                    res.add_damage('bad_length', pos, 'invalid RDW; resynchronised at record %d' % later, True)
                    framing_lost = True
                    pos = later
                    continue
                if stop > end or pos + 4 == end:
                    if not already_truncated:
                        res.add_damage('truncated', pos, 'record extends beyond file/block boundary', True)
                    truncated = True
                else:
                    res.add_damage('bad_length', pos, 'invalid RDW; no later schema-consistent record', True)
                    framing_lost = True
                break
            consume(data[pos+4:stop], pos, parent_issues)
            pos = stop

    if layout == 'V':
        read_region(0, size)
    else:
        pos = 0
        while pos < size:
            if pos + 4 > size:
                res.add_damage('truncated', pos, 'file ends inside a block descriptor', True)
                truncated = True
                break
            length = int.from_bytes(data[pos:pos+2], 'big')
            end = pos + length
            reserved_ok = data[pos+2:pos+4] == b'\0\0'
            boundary_ok = end == size or (end < size and _block_at(data, end) is not None)
            issues = []
            cut = False
            if length < 9 or not reserved_ok or not boundary_ok:
                later = _next_block(data, pos + 4)
                if later is not None:
                    end = later
                    res.add_damage('bad_length', pos, 'invalid BDW; next credible block at %d' % later, True)
                    issues = ['bad_length']
                    framing_lost = True
                elif end > size:
                    end = size
                    res.add_damage('truncated', pos, 'declared block extends beyond file', True)
                    issues = ['truncated']
                    truncated = cut = True
                else:
                    # With no trustworthy boundary, only schema-checked RDWs can be recovered.
                    end = size
                    res.add_damage('bad_length', pos, 'invalid BDW; scanning remaining RDWs conservatively', True)
                    issues = ['bad_length']
                    framing_lost = True
            read_region(pos + 4, end, issues, cut)
            pos = end

    if trailer is not None and not truncated and not framing_lost:
        if trailer[0] != d_count:
            res.add_damage('count_mismatch', 0, 'trailer says %d records, %d found' % (trailer[0], d_count), d_count < trailer[0])
        if trailer[1] != credits_sum:
            res.add_damage('checksum_mismatch', 0, 'trailer credits total %d, records sum to %d' % (trailer[1], credits_sum), False)
            # The total cannot identify which credit value, or the trailer, was damaged.
            for rec in res.records:
                unverified(rec, 'checksum_mismatch')
    elif trailer is None and not truncated and not framing_lost:
        res.add_damage('truncated', size, 'trailer record missing', True)
    if not res.records and res.damage:
        res.status = 'failed'
    elif res.damage:
        res.status = 'partial'
    return res
