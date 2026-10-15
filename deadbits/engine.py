"""Single entry point. Never raises: any failure becomes a contract-shaped Result."""
import math
import re
from pathlib import Path

from .formats import bravo, cvt, ebcdic_dump, lablog, libra98, pak, vault, wad, wks, wpd
from .model import Result

ADAPTERS = [libra98, lablog, vault, wks, ebcdic_dump, cvt, pak, wad, wpd, bravo]          # each: NAME, detect(data)->0..1, decode(data, source_file)->Result
THRESHOLD = 0.5


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    return -sum(c / len(data) * math.log2(c / len(data)) for c in counts if c)


def unrecognized(data: bytes, name: str) -> Result:
    res = Result(name, "UNKNOWN", "unrecognized")
    res.size = len(data)
    res.metadata = {
        "size": len(data),
        "first_64_bytes_hex": data[:64].hex(),
        "printable_strings": [s.decode("latin-1") for s in re.findall(rb"[ -~]{4,}", data)][:10],
        "entropy_bits_per_byte": round(_entropy(data), 2),
    }
    return res


def salvage_bytes(data: bytes, name: str) -> Result:
    scored = []
    for mod in ADAPTERS:
        try:
            scored.append((mod.detect(data), mod))
        except Exception:  # noqa: BLE001 - a broken detector must not hide the others
            scored.append((0.0, mod))
    score, mod = max(scored, key=lambda s: s[0]) if scored else (0.0, None)
    if mod is None or score < THRESHOLD:
        return unrecognized(data, name)
    try:
        res = mod.decode(data, name)
        res.size = len(data)
        return res
    except Exception as exc:  # noqa: BLE001
        res = Result(name, mod.NAME, "failed")
        res.size = len(data)
        res.add_damage("unparsed_bytes", 0, "decoder error: %s" % type(exc).__name__, True)
        res.notes.append("decoder exception: %r" % (exc,))
        return res


def salvage_file(path) -> Result:
    p = Path(path)
    try:
        return salvage_bytes(p.read_bytes(), p.name)
    except Exception as exc:  # noqa: BLE001 - e.g. unreadable file
        res = Result(p.name, "UNKNOWN", "failed")
        res.notes.append("could not read file: %r" % (exc,))
        return res
