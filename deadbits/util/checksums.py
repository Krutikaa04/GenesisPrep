"""Candidate checksum functions + a finder. Used by tools/analyze.py and format decoders."""
import zlib


def sum8(d): return sum(d) & 0xFF
def sum8_neg(d): return (-sum(d)) & 0xFF
def sum16(d): return sum(d) & 0xFFFF
def xor8(d):
    x = 0
    for b in d:
        x ^= b
    return x


def _crc16(d, poly, init, reflect):
    crc = init
    for b in d:
        if reflect:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
        else:
            crc ^= b << 8
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def crc16_ccitt_false(d): return _crc16(d, 0x1021, 0xFFFF, False)
def crc16_xmodem(d): return _crc16(d, 0x1021, 0x0000, False)
def crc16_arc(d): return _crc16(d, 0xA001, 0x0000, True)
def crc16_modbus(d): return _crc16(d, 0xA001, 0xFFFF, True)
def crc32(d): return zlib.crc32(d) & 0xFFFFFFFF
def adler32(d): return zlib.adler32(d) & 0xFFFFFFFF


# name -> (function, width in bytes)
CANDIDATES = {
    "sum8": (sum8, 1), "sum8_neg": (sum8_neg, 1), "xor8": (xor8, 1),
    "sum16": (sum16, 2), "crc16_ccitt_false": (crc16_ccitt_false, 2),
    "crc16_xmodem": (crc16_xmodem, 2), "crc16_arc": (crc16_arc, 2), "crc16_modbus": (crc16_modbus, 2),
    "crc32": (crc32, 4), "adler32": (adler32, 4),
}


def find_matches(region: bytes, stored: bytes) -> list:
    """Which candidates over `region` produce the `stored` value (either byte order)?"""
    out = []
    for name, (fn, width) in CANDIDATES.items():
        if width != len(stored):
            continue
        v = fn(region)
        for endian in ("little", "big"):
            if v == int.from_bytes(stored, endian):
                out.append((name, endian))
    return out
