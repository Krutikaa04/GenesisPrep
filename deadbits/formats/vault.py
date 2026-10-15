"""VAULT: school-office archive utility ("notes and scans in one container").

Layout (little-endian), derived from s08-s10 and confirmed on s08 (expected_outputs); on s09/s10 the
index `size` field independently verifies every decoded payload:

  header (16): "VLT1" | count u16 | xor_key u8 | flags u8 | index_off u32 | names_off u32
               header flags bit0: the name-length bytes in the names table are XORed with xor_key
  blocks     : from 0x10: "BL" | id u16 | payload            (stored_len in the index includes these 4 bytes)
  names      : at names_off; pascal strings, bytes XOR (xor_key + i) & 0xFF
  index      : at index_off; count x 16 bytes:
               id u16 | type u8 (1 text, 2 bitmap, 3 binary) | flags u8 (bit0 RLE90, bit1 XOR)
               | name_off u32 (into names) | block_off u32 | stored_len u16 | size u16 (decoded length)
  payload    : XOR (xor_key + i) when flags bit1, RLE90 (0x90 n = repeat previous n times) when bit0
               bitmap decoded payload = width u8, height u8, width*height pixel bytes

Damage policy (M2).  The index `size` is the only integrity check VAULT offers, so a record is `verified`
only when ALL of the following hold; otherwise it is kept but flagged `verified: false` + `issues`:
  * its block header ("BL" + id) matches the index entry and the block lies inside the file, outside the
    index table;
  * the decoded payload length equals the index `size` (when it does not, no sha256 is emitted: a hash of
    a payload that is known to be the wrong length cannot match and would only look authoritative);
  * the name is printable text, and a text entry decodes to text without control characters (a wrong
    xor_key / flipped flag produces length-correct garbage that the size check alone cannot see).
If the index itself is lost (index_off outside the file) nothing is salvaged: the type, flags and names of
every block live only in the index, so any record would be a guess -> `failed` + `index_missing`.
"""
import hashlib
import struct

from ..model import Result, unverified
from ..util.rle import rle90

NAME = "VAULT"
MAGIC = b"VLT1"
HEADER_LEN = 16
ENTRY_LEN = 16
TYPES = {1: "text", 2: "bitmap", 3: "binary"}
TEXT_OK_CONTROLS = {9, 10, 13}


def detect(data: bytes) -> float:
    if data[:4] != MAGIC:
        return 0.0
    if len(data) >= HEADER_LEN:
        idx, names = struct.unpack_from("<II", data, 8)
        if HEADER_LEN <= idx <= len(data) and HEADER_LEN <= names <= len(data):
            return 1.0
    return 0.7


def _xor(buf: bytes, key: int) -> bytes:
    return bytes(b ^ ((key + i) & 0xFF) for i, b in enumerate(buf))


def _decode_payload(payload: bytes, flags: int, key: int, want: int):
    """Try XOR->RLE then RLE->XOR; return (decoded, verified) where verified means len == index size."""
    candidates = []
    if flags & 2 and flags & 1:
        for order in ("xor_rle", "rle_xor"):
            try:
                a = rle90(_xor(payload, key)) if order == "xor_rle" else _xor(rle90(payload), key)
                candidates.append(a)
            except ValueError:
                pass
    elif flags & 1:
        try:
            candidates.append(rle90(payload))
        except ValueError:
            pass
    elif flags & 2:
        candidates.append(_xor(payload, key))
    else:
        candidates.append(payload)
    for c in candidates:
        if len(c) == want:
            return c, True
    return (candidates[0] if candidates else None), False


def _printable_name(name: str) -> bool:
    return name != "" and name.isprintable()


def _text_plausible(raw: bytes) -> bool:
    return not any(b < 32 and b not in TEXT_OK_CONTROLS or b == 127 for b in raw)


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res
    count, key, hflags = struct.unpack_from("<HBB", data, 4)
    index_off, names_off = struct.unpack_from("<II", data, 8)
    res.metadata = {"entry_count": count, "xor_key": key, "flags": hflags}

    if index_off < HEADER_LEN or index_off > size:
        res.status = "failed"
        res.add_damage("index_missing", 8, "index offset %d is outside the file (size %d)" % (index_off, size), True)
        if index_off > size:
            res.add_damage("truncated", size, "file ends before the index", True)
        return res

    # --- index ---------------------------------------------------------------------------------
    avail = (size - index_off) // ENTRY_LEN
    n = min(count, avail)
    if n < count:
        kind = "truncated" if (size - index_off) % ENTRY_LEN else "count_mismatch"
        res.add_damage(kind, size if kind == "truncated" else 4,
                       "index holds %d of %d declared entries" % (n, count), True)
    elif size - (index_off + count * ENTRY_LEN) > 0:
        res.add_damage("unparsed_bytes", index_off + count * ENTRY_LEN,
                       "%d bytes after the index" % (size - index_off - count * ENTRY_LEN), False)
    index_end = index_off + n * ENTRY_LEN
    names_ok = HEADER_LEN <= names_off <= size
    if not names_ok:      # root cause once, not once per entry
        res.add_damage("oob_pointer", 12, "names offset %d is outside the file (size %d): no names can be read" %
                       (names_off, size), True)

    def read_name(off):
        p = names_off + off
        if not names_ok or p >= size:
            return None
        ln = data[p] ^ (key if hflags & 1 else 0)
        raw = data[p + 1:p + 1 + ln]
        if len(raw) != ln:
            return None
        return _xor(raw, key).decode("latin-1")

    unverified_any = False
    seen_ids = set()
    for i in range(n):
        epos = index_off + i * ENTRY_LEN
        eid, typ, eflags, name_off, boff, stored, esize = struct.unpack_from("<HBBIIHH", data, epos)
        rec = {"id": eid, "name": read_name(name_off), "type": TYPES.get(typ, "binary"), "size": esize}
        issues = []

        def flag(kind, offset, detail, lossy=True):
            res.add_damage(kind, offset, detail, lossy)
            if kind not in issues:
                issues.append(kind)

        if rec["name"] is None:
            if names_ok:
                flag("oob_pointer", epos + 4, "name offset %d outside names table" % name_off)
            else:
                issues.append("oob_pointer")
        elif not _printable_name(rec["name"]):
            flag("invalid_value", epos + 4, "name of entry %d is not printable text (wrong xor_key or corrupted)" % eid)
        if typ not in TYPES:
            flag("invalid_value", epos + 2, "unknown entry type %d" % typ, False)
        if eid in seen_ids:
            flag("invalid_value", epos, "duplicate entry id %d" % eid, False)
        seen_ids.add(eid)
        rec["compressed"] = bool(eflags & 1)
        end = boff + stored
        if boff < HEADER_LEN or end > size or stored < 4:
            flag("oob_pointer", epos + 8, "block of entry %d at %d (+%d) is outside the file" % (eid, boff, stored))
            unverified(rec, *issues)
            res.records.append(rec)
            unverified_any = True
            continue
        if boff < index_end and end > index_off:
            flag("oob_pointer", epos + 8, "block of entry %d overlaps the index table" % eid)
            unverified(rec, *issues)
            res.records.append(rec)
            unverified_any = True
            continue
        if data[boff:boff + 2] != b"BL" or struct.unpack_from("<H", data, boff + 2)[0] != eid:
            flag("oob_pointer", boff, "block header at %d does not match entry %d" % (boff, eid))
            unverified(rec, *issues)
            res.records.append(rec)
            unverified_any = True
            continue
        decoded, ok = _decode_payload(data[boff + 4:end], eflags, key, esize)
        if decoded is None:
            flag("bad_length", boff, "payload of entry %d cannot be decoded" % eid)
            unverified(rec, *issues)
            res.records.append(rec)
            unverified_any = True
            continue
        if not ok:
            flag("bad_length", boff, "decoded payload is %d bytes, index says %d" % (len(decoded), esize))
        else:
            rec["sha256"] = hashlib.sha256(decoded).hexdigest()
        if typ == 1:
            if ok and not _text_plausible(decoded):
                flag("invalid_value", boff, "text of entry %d contains control characters (wrong xor_key or "
                     "corrupted payload)" % eid)
            try:
                rec["text"] = decoded.decode("utf-8")
            except UnicodeDecodeError:
                rec["text"] = decoded.decode("cp437")
        elif typ == 2 and len(decoded) >= 2:
            rec["width"], rec["height"] = decoded[0], decoded[1]
            if ok and len(decoded) != 2 + decoded[0] * decoded[1]:
                flag("invalid_value", boff, "bitmap of entry %d is %d bytes, %dx%d needs %d" %
                     (eid, len(decoded), decoded[0], decoded[1], 2 + decoded[0] * decoded[1]), False)
        if issues:
            unverified(rec, *issues)
            unverified_any = True
        res.records.append(rec)

    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
