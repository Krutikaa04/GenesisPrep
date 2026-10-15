"""PAK: Quake-style game archive.

  header (12): "PACK" | dir_off u32 | dir_len u32
  entry (64) : name char[56] (NUL-terminated) | offset u32 | size u32
Entries are independent (the directory gives every offset/size), so one bad entry never costs the
rest. There is no per-entry checksum: sha256 is computed over the extracted bytes and a corrupted
payload that is still in bounds cannot be detected. Confirmed on s24.
"""
import hashlib
import struct

from ..model import Result, unverified

NAME = "PAK"
MAGIC = b"PACK"
HEADER_LEN = 12
ENTRY_LEN = 64


def detect(data: bytes) -> float:
    if data[:4] != MAGIC:
        return 0.0
    if len(data) >= HEADER_LEN:
        off, ln = struct.unpack_from("<II", data, 4)
        if HEADER_LEN <= off <= len(data) and ln % ENTRY_LEN == 0:
            return 1.0
    return 0.7


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
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
    n = min(declared, avail)
    if n < declared:
        kind = "truncated" if (size - dir_off) % ENTRY_LEN else "count_mismatch"
        res.add_damage(kind, size if kind == "truncated" else 8,
                       "directory holds %d of %d declared entries" % (n, declared), True)
    elif size > dir_off + dir_len:
        res.add_damage("unparsed_bytes", dir_off + dir_len, "%d bytes after the directory" %
                       (size - dir_off - dir_len), False)

    unverified_any = False
    for i in range(n):
        base = dir_off + i * ENTRY_LEN
        raw_name = data[base:base + 56].split(b"\0")[0]
        off, sz = struct.unpack_from("<II", data, base + 56)
        rec = {"name": raw_name.decode("latin-1"), "offset": off, "size": sz}
        issues = []
        if not raw_name:
            issues.append("invalid_value")
            res.add_damage("invalid_value", base, "entry %d has an empty name" % i, False)
        if off < HEADER_LEN or off + sz > size or (off < dir_off + dir_len and off + sz > dir_off):
            issues.append("oob_pointer")
            res.add_damage("oob_pointer", base + 56, "entry %r: data at %d (+%d) is outside the file or overlaps the directory"
                           % (rec["name"], off, sz), True)
        else:
            rec["sha256"] = hashlib.sha256(data[off:off + sz]).hexdigest()
        if issues:
            unverified(rec, *issues)
            unverified_any = True
        res.records.append(rec)

    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
