"""PAK: Quake-style game archive.

  header (12): "PACK" | dir_off u32 | dir_len u32
  entry (64) : name char[56] (NUL-terminated) | offset u32 | size u32
Entries are independent (the directory gives every offset/size), so one bad entry never costs the
rest. There is no per-entry checksum: sha256 is computed over the extracted bytes and a corrupted
payload that is still in bounds cannot be detected. Confirmed on s24.
"""
import struct

from ..model import Result, unverified
from ._archive import PayloadHashes, bounded_count, credible_name, note_ambiguities

NAME = "PAK"
MAGIC = b"PACK"
HEADER_LEN = 12
ENTRY_LEN = 64


def detect(data: bytes) -> float:
    if data[:4] != MAGIC or len(data) < HEADER_LEN:
        return 0.0
    off, ln = struct.unpack_from("<II", data, 4)
    if not HEADER_LEN <= off <= len(data):
        return 0.0
    if ln % ENTRY_LEN == 0 and off + ln <= len(data):
        return 1.0
    # A damaged length can still be identified by an independent directory
    # entry. Look at at most eight complete entries, never the declared count.
    for i in range(min(8, (len(data) - off) // ENTRY_LEN)):
        base = off + i * ENTRY_LEN
        raw_name = data[base:base + 56].split(b"\0", 1)[0]
        start, size = struct.unpack_from("<II", data, base + 56)
        if credible_name(raw_name) and (not size or HEADER_LEN <= start <= off - size):
            return 0.8
    return 0.0


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res
    if data[:4] != MAGIC:
        res.status = "failed"
        res.add_damage("invalid_value", 0, "invalid PAK magic", True)
        return res
    dir_off, dir_len = struct.unpack_from("<II", data, 4)
    res.metadata = {"directory_offset": dir_off, "directory_length": dir_len,
                    "declared_entries": dir_len // ENTRY_LEN}
    if dir_off < HEADER_LEN or dir_off > size:
        res.status = "failed"
        res.add_damage("index_missing", 4, "directory offset %d is outside the file (size %d)" % (dir_off, size), True)
        if dir_off > size:
            res.add_damage("truncated", size, "file ends before the directory", True)
        return res
    if dir_len % ENTRY_LEN:
        res.add_damage("bad_length", 8, "directory length %d is not a multiple of %d" % (dir_len, ENTRY_LEN), False)
    declared = dir_len // ENTRY_LEN
    avail = (size - dir_off) // ENTRY_LEN
    physically_present = min(declared, avail)
    n = bounded_count(res, declared, avail, dir_off)
    if physically_present < declared:
        kind = "truncated" if (size - dir_off) % ENTRY_LEN else "count_mismatch"
        res.add_damage(kind, size if kind == "truncated" else 8,
                       "directory holds %d of %d declared entries" % (physically_present, declared), True)
    elif size > dir_off + dir_len:
        res.add_damage("unparsed_bytes", dir_off + dir_len, "%d bytes after the directory" %
                       (size - dir_off - dir_len), False)

    hashes = PayloadHashes(data, res)
    entries = []
    dir_end = min(size, dir_off + dir_len)
    for i in range(n):
        base = dir_off + i * ENTRY_LEN
        raw_name = data[base:base + 56].split(b"\0", 1)[0]
        off, sz = struct.unpack_from("<II", data, base + 56)
        rec = {"name": raw_name.decode("latin-1"), "offset": off, "size": sz}
        issues = []
        if not credible_name(raw_name):
            issues.append("invalid_value")
            res.add_damage("invalid_value", base, "entry %d has an empty or control-containing name" % i, False)
        span = None
        if sz and (off < HEADER_LEN or off + sz > size or (off < dir_end and off + sz > dir_off)):
            issues.append("oob_pointer")
            res.add_damage("oob_pointer", base + 56, "entry %r: data at %d (+%d) is outside the file or overlaps the directory"
                           % (rec["name"], off, sz), True)
        else:
            hashes.add(rec, base + 56)
            span = (off, off + sz)
        if issues:
            unverified(rec, *issues)
        res.records.append(rec)
        entries.append((base, span))

    note_ambiguities(res, entries)

    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage:
        res.status = "partial"
    return res
