"""Byte-analysis helper for cracking undocumented formats.

  python tools/analyze.py info  FILE...            size, entropy, first bytes, strings
  python tools/analyze.py diff  FILE FILE...       constant vs varying byte offsets across files
  python tools/analyze.py csum  FILE...            whole-file checksum hypotheses (stored at end / start)
  python tools/analyze.py block FILE --size N [--skip H] [--width W]   per-block checksum hypotheses
  python tools/analyze.py rle   FILE --expect N    which RLE variants give N output bytes
  python tools/analyze.py xor   FILE               rank XOR keys by text-likeness
Log what you try (and what failed) in FIELD-LOG.md.
"""
import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deadbits.util import checksums, rle, xor  # noqa: E402


def entropy(d):
    if not d:
        return 0.0
    c = [0] * 256
    for b in d:
        c[b] += 1
    return -sum(x / len(d) * math.log2(x / len(d)) for x in c if x)


def hexdump(d, n=64):
    return " ".join("%02x" % b for b in d[:n])


def cmd_info(a):
    for f in a.files:
        d = Path(f).read_bytes()
        print("%s: %d bytes, entropy %.2f bits/byte" % (f, len(d), entropy(d)))
        print("  first bytes:", hexdump(d))
        print("  strings:", [s.decode("latin-1") for s in re.findall(rb"[ -~]{4,}", d)][:15])


def cmd_diff(a):
    ds = [Path(f).read_bytes() for f in a.files]
    n = min(len(d) for d in ds)
    const = [i for i in range(n) if len({d[i] for d in ds}) == 1]
    runs, start = [], None
    for i in range(n + 1):
        if i < n and i in set(const):
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i)); start = None
    print("sizes:", [len(d) for d in ds])
    print("constant runs (likely magic/header constants), [start,end):")
    for s, e in runs[:40]:
        print("  %5d-%5d  %s" % (s, e, hexdump(ds[0][s:e], 24)))
    var = [i for i in range(min(n, 128)) if i not in set(const)]
    print("varying offsets in first 128 bytes (counts/lengths/ids/dates?):", var)
    for off in var[:12]:
        print("  @%d: %s" % (off, [d[off] for d in ds]))


def cmd_csum(a):
    ds = [Path(f).read_bytes() for f in a.files]
    score = {}
    for d in ds:
        for w in (1, 2, 4):
            if len(d) <= w:
                continue
            for where, stored, region in (("end", d[-w:], d[:-w]), ("start", d[:w], d[w:])):
                for name, endian in checksums.find_matches(region, stored):
                    score.setdefault((name, endian, where), 0)
                    score[(name, endian, where)] += 1
    print("whole-file checksum hits (must equal %d to be convincing):" % len(ds))
    for k, v in sorted(score.items(), key=lambda kv: -kv[1]):
        print("  %-20s %-7s stored@%-5s %d/%d" % (k[0], k[1], k[2], v, len(ds)))
    if not score:
        print("  none")


def cmd_block(a):
    d = Path(a.file).read_bytes()[a.skip:]
    blocks = [d[i:i + a.size] for i in range(0, len(d) - a.size + 1, a.size)]
    print("%d blocks of %d bytes (skip %d)" % (len(blocks), a.size, a.skip))
    for name, (fn, width) in checksums.CANDIDATES.items():
        if a.width and width != a.width:
            continue
        for endian in ("little", "big"):
            for where in ("end", "start"):
                ok = 0
                for b in blocks:
                    stored, region = (b[-width:], b[:-width]) if where == "end" else (b[:width], b[width:])
                    if fn(region) == int.from_bytes(stored, endian):
                        ok += 1
                if ok:
                    print("  %-20s %-7s stored@%-5s %d/%d blocks" % (name, endian, where, ok, len(blocks)))


def cmd_rle(a):
    print(rle.try_all(Path(a.file).read_bytes(), a.expect) or "no variant gives %d bytes" % a.expect)


def cmd_xor(a):
    d = Path(a.file).read_bytes()
    print("single-byte (key, score, preview):")
    for r in xor.single_byte(d):
        print("  0x%02x %.3f %r" % r)
    print("repeating (len, key, score, preview):")
    for r in xor.repeating(d):
        print("  %d %s %.3f %r" % (r[0], r[1].hex(), r[2], r[3]))
    print("position-keyed (key, score):", xor.position_keyed(d))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("info", cmd_info), ("diff", cmd_diff), ("csum", cmd_csum)):
        p = sub.add_parser(name); p.add_argument("files", nargs="+"); p.set_defaults(fn=fn)
    p = sub.add_parser("block"); p.add_argument("file"); p.add_argument("--size", type=int, required=True)
    p.add_argument("--skip", type=int, default=0); p.add_argument("--width", type=int, default=0); p.set_defaults(fn=cmd_block)
    p = sub.add_parser("rle"); p.add_argument("file"); p.add_argument("--expect", type=int, required=True); p.set_defaults(fn=cmd_rle)
    p = sub.add_parser("xor"); p.add_argument("file"); p.set_defaults(fn=cmd_xor)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
