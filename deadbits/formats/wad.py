"""WAD: Doom-style game archive.

  header (12): "IWAD"|"PWAD" | numlumps u32 | dir_off u32
  entry (16) : offset u32 | size u32 | name char[8] (NUL-terminated; bytes after the NUL are ignored)
Entries are independent; marker lumps have size 0. No per-lump checksum. Confirmed on s23.
"""
import hashlib
import struct

from ..model import Result, unverified

NAME = "WAD"
HEADER_LEN = 12
ENTRY_LEN = 16


def detect(data: bytes) -> float:
    if data[:4] not in (b"IWAD", b"PWAD"):
        return 0.0
    if len(data) >= HEADER_LEN:
        n, off = struct.unpack_from("<II", data, 4)
        if HEADER_LEN <= off <= len(data) and n <= 65535:
            return 1.0
    return 0.7


def decode(data: bytes, name: str) -> Result:
    res = Result(name, NAME, "ok")
    size = len(data)
    if size < HEADER_LEN:
        res.status = "failed"
        res.add_damage("truncated", size, "header truncated: %d of %d bytes" % (size, HEADER_LEN), True)
        return res
    numlumps, dir_off = struct.unpack_from("<II", data, 4)
    res.metadata = {"wad_type": data[:4].decode("ascii"), "lump_count": numlumps, "directory_offset": dir_off}
    if dir_off < HEADER_LEN or dir_off > size:
        res.status = "failed"
        res.add_damage("index_missing", 8, "directory offset %d is outside the file (size %d)" % (dir_off, size), True)
        if dir_off > size:
            res.add_damage("truncated", size, "file ends before the directory", True)
        return res
    avail = (size - dir_off) // ENTRY_LEN
    n = min(numlumps, avail)
    if n < numlumps:
        # a cut file normally ends mid-entry; a directory that ends on an entry boundary points at a bad count
        kind = "truncated" if (size - dir_off) % ENTRY_LEN else "count_mismatch"
        res.add_damage(kind, size if kind == "truncated" else 4,
                       "directory holds %d of %d declared lumps" % (n, numlumps), True)
    elif size > dir_off + numlumps * ENTRY_LEN:
        res.add_damage("unparsed_bytes", dir_off + numlumps * ENTRY_LEN, "%d bytes after the directory" %
                       (size - dir_off - numlumps * ENTRY_LEN), False)

    unverified_any = False
    dir_end = dir_off + numlumps * ENTRY_LEN
    for i in range(n):
        base = dir_off + i * ENTRY_LEN
        off, sz = struct.unpack_from("<II", data, base)
        raw_name = data[base + 8:base + 16].split(b"\0")[0]
        rec = {"name": raw_name.decode("latin-1"), "offset": off, "size": sz}
        issues = []
        if sz and (off < HEADER_LEN or off + sz > size or (off < dir_end and off + sz > dir_off)):
            issues.append("oob_pointer")
            res.add_damage("oob_pointer", base, "lump %r: data at %d (+%d) is outside the file or overlaps the directory"
                           % (rec["name"], off, sz), True)
        else:
            rec["sha256"] = hashlib.sha256(data[off:off + sz] if sz else b"").hexdigest()
        if issues:
            unverified(rec, *issues)
            unverified_any = True
        res.records.append(rec)

    if not res.records and res.damage:
        res.status = "failed"
    elif res.damage or unverified_any:
        res.status = "partial"
    return res
