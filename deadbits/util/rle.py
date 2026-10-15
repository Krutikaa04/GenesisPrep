"""Run-length decoder variants. try_all() returns the variants whose output size matches."""


def pairs_count_first(d):
    if len(d) % 2:
        raise ValueError("odd length")
    return b"".join(bytes([d[i + 1]]) * d[i] for i in range(0, len(d), 2))


def pairs_byte_first(d):
    if len(d) % 2:
        raise ValueError("odd length")
    return b"".join(bytes([d[i]]) * d[i + 1] for i in range(0, len(d), 2))


def packbits(d):
    out, i = bytearray(), 0
    while i < len(d):
        n = d[i]
        i += 1
        if n < 128:
            if i + n + 1 > len(d):
                raise ValueError("literal overruns input")
            out += d[i:i + n + 1]
            i += n + 1
        elif n > 128:
            if i >= len(d):
                raise ValueError("repeat overruns input")
            out += bytes([d[i]]) * (257 - n)
            i += 1
    return bytes(out)


def escape_byte(d, esc):
    """esc, count, byte -> repeat; esc, 0 -> literal esc; anything else literal."""
    out, i = bytearray(), 0
    while i < len(d):
        b = d[i]
        if b != esc:
            out.append(b)
            i += 1
            continue
        if i + 1 >= len(d):
            raise ValueError("dangling escape")
        n = d[i + 1]
        if n == 0:
            out.append(esc)
            i += 2
        else:
            if i + 2 >= len(d):
                raise ValueError("escape overruns input")
            out += bytes([d[i + 2]]) * n
            i += 3
    return bytes(out)


def try_all(data: bytes, expected_size: int) -> list:
    hits = []
    fixed = {"pairs_count_byte": pairs_count_first, "pairs_byte_count": pairs_byte_first, "packbits": packbits}
    for name, fn in fixed.items():
        try:
            if len(fn(data)) == expected_size:
                hits.append(name)
        except ValueError:
            pass
    for esc in range(256):
        try:
            if len(escape_byte(data, esc)) == expected_size:
                hits.append("escape_0x%02x" % esc)
        except ValueError:
            pass
    return hits


def packbits_encode(d: bytes) -> bytes:
    out, i, n = bytearray(), 0, len(d)
    while i < n:
        run = 1
        while i + run < n and d[i + run] == d[i] and run < 128:
            run += 1
        if run >= 3:
            out += bytes([257 - run, d[i]])
            i += run
            continue
        j = i
        while j < n and j - i < 128 and not (j + 2 < n and d[j] == d[j + 1] == d[j + 2]):
            j += 1
        j = max(j, i + 1)
        out += bytes([j - i - 1]) + d[i:j]
        i = j
    return bytes(out)


def pairs_encode(d: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(d):
        run = 1
        while i + run < len(d) and d[i + run] == d[i] and run < 255:
            run += 1
        out += bytes([run, d[i]])
        i += run
    return bytes(out)


def rle90(d: bytes) -> bytes:
    """BinHex-style RLE90: 0x90 n  -> previous byte repeated n times in total; 0x90 0x00 -> literal 0x90."""
    out, i, last = bytearray(), 0, None
    while i < len(d):
        b = d[i]
        if b != 0x90:
            out.append(b)
            last = b
            i += 1
            continue
        if i + 1 >= len(d):
            raise ValueError("dangling RLE escape")
        n = d[i + 1]
        if n == 0:
            out.append(0x90)
            last = 0x90
        else:
            if last is None:
                raise ValueError("RLE repeat with no previous byte")
            out.extend(bytes([last]) * (n - 1))
        i += 2
    return bytes(out)
