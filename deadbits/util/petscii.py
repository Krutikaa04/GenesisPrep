"""PETSCII (Commodore 64, lower/upper-case set) -> text.

0x41-0x5A are LOWER-case letters and 0xC1-0xDA are UPPER-case (confirmed on s18: "Notes v2",
"Text Scrap"). 0x0D is a carriage return (-> newline); 0xA0 is the shifted space used as padding.
Bytes with no text equivalent (graphics) become U+FFFD so nothing is silently invented.
"""


def char(b: int) -> str:
    if b == 0x0D:
        return "\n"
    if b == 0xA0:
        return " "
    if 0x41 <= b <= 0x5A:
        return chr(b + 0x20)          # lower case
    if 0xC1 <= b <= 0xDA:
        return chr(b - 0x80)          # upper case
    if 0x20 <= b <= 0x40 or b in (0x5B, 0x5D):
        return chr(b)
    if b in (0x09, 0x0A):
        return chr(b)
    return "�"


def decode(raw: bytes) -> str:
    return "".join(char(b) for b in raw)


def decode_field(raw: bytes) -> str:
    """Fixed-width name field: stop at NUL, drop shifted-space padding."""
    raw = raw.split(b"\0")[0]
    return decode(raw).rstrip(" ")
