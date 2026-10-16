"""Bounded common work for the independent PAK/WAD directory adapters.

These archives have no checksums. Directory facts are retained when ambiguous;
structural warnings and safety limits must not turn guesses into verified hashes.
"""
import hashlib

from ..model import unverified

MAX_ENTRIES = 100_000
HASH_WORK_FACTOR = 4


def bounded_count(res, declared, available, offset):
    """Cap physical directory work and explicitly report any resource exclusion."""
    count = min(declared, available, MAX_ENTRIES)
    if count < min(declared, available):
        res.add_damage("bad_length", offset,
                       "directory safety budget: decoded %d of %d physically available entries"
                       % (count, min(declared, available)), True)
    return count


class PayloadHashes:
    """No payload copies; aliases share a digest and unique ranges share a byte budget."""

    def __init__(self, data, res):
        self.data = memoryview(data)
        self.res = res
        self.remaining = HASH_WORK_FACTOR * len(data)
        self.cache = {}
        self.reported = False

    def add(self, rec, offset):
        span = (rec["offset"], rec["size"])
        # Every zero-byte marker has the same independently known empty payload.
        if not span[1]:
            span = (0, 0)
        if span in self.cache:
            rec["sha256"] = self.cache[span]
        elif span[1] <= self.remaining:
            self.remaining -= span[1]
            start, length = span
            digest = hashlib.sha256(self.data[start:start + length]).hexdigest()
            self.cache[span] = digest
            rec["sha256"] = digest
        else:
            unverified(rec, "bad_length")
            if not self.reported:
                self.res.add_damage("bad_length", offset,
                                    "payload hash safety budget exhausted; affected entries retain "
                                    "directory facts without sha256", True)
                self.reported = True


def note_ambiguities(res, entries):
    """Keep all records; flag duplicate names and overlapping valid payloads.

    entries contains (directory byte offset, valid payload range or None).
    Sorting and a monotone interval sweep avoid checking every pair of entries.
    """
    names = {}
    duplicates = {}
    spans = []
    for index, (base, span) in enumerate(entries):
        rec = res.records[index]
        name = rec["name"]
        if name in names:
            first = names[name]
            unverified(res.records[first], "invalid_value")
            unverified(rec, "invalid_value")
            duplicates[name] = duplicates.get(name, 1) + 1
        else:
            names[name] = index
        if span is not None and span[1] > span[0]:
            spans.append((span[0], span[1], index))
    for name, count in duplicates.items():
        res.add_damage("invalid_value", entries[names[name]][0],
                       "%d entries share name %r; all are retained" % (count, name), False)

    spans.sort()
    group = []
    end = -1

    def finish_group():
        if len(group) > 1:
            for index in group:
                unverified(res.records[index], "invalid_value")
            res.add_damage("invalid_value", entries[group[0]][0],
                           "%d payload ranges overlap; all entries are retained" % len(group), False)

    for start, stop, index in spans:
        if start >= end:
            finish_group()
            group = []
        group.append(index)
        end = max(end, stop)
    finish_group()


def credible_name(raw):
    """Directory evidence for bounded detection, without choosing a text encoding."""
    return bool(raw) and all(value >= 32 and not 127 <= value < 160 for value in raw)
