"""Coherent WKS stream bounds avoid invoking large-file resynchronization."""
from ._large import budget_issue
from .formats import wks


def resource_issue(data, coarse_reason):
    if data[:4] != b"\0\0\x02\0":
        return coarse_reason
    pos, items, output, work = 0, 0, 4096, 4*len(data)
    reason = budget_issue("WKS", work, output, items)
    if reason:
        return reason
    while pos < len(data):
        record = wks._strict_record(data, pos)
        if record is None:
            return coarse_reason
        end, op = record
        items += 1
        length = end-pos-4
        if op in wks.CELL_OPS:
            # Charge every physical assignment, including repeated cell keys.
            output += 1024 + 4*length
        elif op == 8:
            output += 256  # column-width keys can accumulate
        elif op not in wks.EXPECT_LEN and op not in wks.KNOWN_META:
            output += 512  # one unknown-record damage object, not a free skip
        reason = budget_issue("WKS", work, output, items)
        if reason:
            return reason
        if op == 1:
            return None if end == len(data) else coarse_reason
        pos = end
    return coarse_reason  # no proved EOF; do not start resynchronization
