"""MS-DOS packed date/time words (little-endian u16)."""
import datetime


def date_parts(word: int):
    """-> (year, month, day) or None if the word is not a valid calendar date."""
    y, m, d = (word >> 9) + 1980, (word >> 5) & 0xF, word & 0x1F
    try:
        datetime.date(y, m, d)
    except ValueError:
        return None
    return y, m, d


def time_parts(word: int):
    h, mi, s = word >> 11, (word >> 5) & 0x3F, (word & 0x1F) * 2
    if h > 23 or mi > 59 or s > 59:
        return None
    return h, mi, s


def iso_date(word: int):
    p = date_parts(word)
    return "%04d-%02d-%02d" % p if p else None


def iso_datetime(date_word: int, time_word: int):
    d, t = date_parts(date_word), time_parts(time_word)
    if not d or not t:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (d + t)
