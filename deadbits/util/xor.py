"""XOR-obfuscation helpers: rank keys by how text-like the output is."""


def printable_score(d: bytes) -> float:
    """Text-likeness prior: lowercase/space/. _ - best, digits and capitals next, other punctuation poor."""
    if not d:
        return 0.0

    def w(b):
        if 97 <= b <= 122 or b in (32, 46, 95, 45):
            return 1.0
        if 65 <= b <= 90:
            return 0.9
        if 48 <= b <= 57:
            return 0.9
        if 33 <= b < 127 or b in (9, 10, 13):
            return 0.2
        return 0.0
    return sum(w(b) for b in d) / len(d)


def single_byte(data: bytes, top: int = 5) -> list:
    ranked = sorted(((printable_score(bytes(b ^ k for b in data)), k) for k in range(256)), reverse=True)
    return [(k, round(s, 3), bytes(b ^ k for b in data)[:40]) for s, k in ranked[:top]]


def repeating(data: bytes, max_len: int = 16) -> list:
    """Best key per key length (per-position best printable score). Text-only heuristic."""
    out = []
    for n in range(2, max_len + 1):
        key = bytearray()
        for pos in range(n):
            col = data[pos::n]
            key.append(max(range(256), key=lambda k: printable_score(bytes(b ^ k for b in col))))
        dec = bytes(b ^ key[i % n] for i, b in enumerate(data))
        out.append((n, bytes(key), round(printable_score(dec), 3), dec[:40]))
    return sorted(out, key=lambda r: -r[2])[:5]


def position_keyed(data: bytes, top: int = 5) -> list:
    """out[i] = in[i] ^ k ^ (i & 0xFF)"""
    ranked = sorted(((printable_score(bytes(b ^ k ^ (i & 0xFF) for i, b in enumerate(data))), k)
                     for k in range(256)), reverse=True)
    return [(k, round(s, 3)) for s, k in ranked[:top]]


def repeating_per_item(items: list, max_len: int = 8, min_samples: int = 4, margin: float = 0.05):
    """Repeating XOR key that restarts at position 0 of every item (e.g. each name).

    Returns (key, score) or None. Needs >= min_samples bytes per key column and a clearly
    text-like result (>= 0.9) where EVERY key byte beats its runner-up by `margin`; otherwise a
    short key could 'fit' any data and we refuse rather than guess.
    """
    if len(items) < min_samples:
        return None
    best = None
    shortest = min(len(i) for i in items)
    for n in range(2, min(max_len, shortest) + 1):
        key = bytearray()
        for j in range(n):
            col = bytes(i[p] for i in items for p in range(j, len(i), n))
            if len(col) < min_samples:
                key = None
                break
            ranked = sorted(((printable_score(bytes(b ^ k for b in col)), k) for k in range(256)), reverse=True)
            if ranked[0][0] - ranked[1][0] < margin:   # near-tie: this key byte would be a guess
                key = None
                break
            key.append(ranked[0][1])
        if key is None:
            continue
        dec = b"".join(bytes(b ^ key[j % n] for j, b in enumerate(i)) for i in items)
        sc = printable_score(dec)
        if sc >= 0.9 and (best is None or sc > best[1] + 0.01):
            best = (bytes(key), round(sc, 3))
    return best
