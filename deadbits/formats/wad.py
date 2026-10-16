"""WAD: Doom-style game archive.

  header (12): "IWAD"|"PWAD" | numlumps u32 | dir_off u32
  entry (16) : offset u32 | size u32 | name char[8] (NUL-terminated; bytes after the NUL are ignored)
Entries are independent; marker lumps have size 0. No per-lump checksum. Confirmed on s23.
"""
import struct

from ..model import Result, unverified
from ._archive import PayloadHashes, bounded_count, credible_name, note_ambiguities

NAME = "WAD"
HEADER_LEN = 12
ENTRY_LEN = 16


def detect(data: bytes) -> float:
    if data[:4] not in (b"IWAD", b"PWAD") or len(data) < HEADER_LEN:
        return 0.0
    n, off = struct.unpack_from("<II", data, 4)
    if not HEADER_LEN <= off <= len(data):
        return 0.0
    if n <= (len(data) - off) // ENTRY_LEN:
        return 1.0
    # Count corruption needs independent, physically present entry evidence.
    for i in range(min(8, (len(data) - off) // ENTRY_LEN)):
        base = off + i * ENTRY_LEN
        start, size = struct.unpack_from("<II", data, base)
        raw_name = data[base + 8:base + 16].split(b"\0", 1)[0]
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
    if data[:4] not in (b"IWAD", b"PWAD"):
        res.status = "failed"
        res.add_damage("invalid_value", 0, "invalid WAD magic", True)
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
    physically_present = min(numlumps, avail)
    n = bounded_count(res, numlumps, avail, dir_off)
    if physically_present < numlumps:
        # a cut file normally ends mid-entry; a directory that ends on an entry boundary points at a bad count
        kind = "truncated" if (size - dir_off) % ENTRY_LEN else "count_mismatch"
        res.add_damage(kind, size if kind == "truncated" else 4,
                       "directory holds %d of %d declared lumps" % (physically_present, numlumps), True)
    elif size > dir_off + numlumps * ENTRY_LEN:
        res.add_damage("unparsed_bytes", dir_off + numlumps * ENTRY_LEN, "%d bytes after the directory" %
                       (size - dir_off - numlumps * ENTRY_LEN), False)

    hashes = PayloadHashes(data, res)
    entries = []
    dir_end = min(size, dir_off + numlumps * ENTRY_LEN)
    for i in range(n):
        base = dir_off + i * ENTRY_LEN
        off, sz = struct.unpack_from("<II", data, base)
        raw_name = data[base + 8:base + 16].split(b"\0", 1)[0]
        rec = {"name": raw_name.decode("latin-1"), "offset": off, "size": sz}
        issues = []
        if not credible_name(raw_name):
            issues.append("invalid_value")
            res.add_damage("invalid_value", base + 8, "lump %d has an empty or control-containing name" % i, False)
        span = None
        if sz and (off < HEADER_LEN or off + sz > size or (off < dir_end and off + sz > dir_off)):
            issues.append("oob_pointer")
            res.add_damage("oob_pointer", base, "lump %r: data at %d (+%d) is outside the file or overlaps the directory"
                           % (rec["name"], off, sz), True)
        else:
            hashes.add(rec, base)
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
