"""CVT selected-text bounds; sequential slots cannot alias or decompress."""
from ._large import budget_issue


def resource_issue(data, coarse_reason):
    if len(data) < 508 or data[34:55] != b"formatted GEOS file V" or data[21] not in (0, 1):
        return coarse_reason
    work, output, items = 0, 1536, 0
    if data[21] == 0:
        declared = int.from_bytes(data[28:30], "little")
        end = min(len(data), (1 + declared) * 254) if declared else len(data)
        selected = max(0, end - 508)
        work, output, items = 6 * selected, output + 4 * selected, 1
    else:
        if len(data) < 762:
            return coarse_reason
        pos = 762
        for slot in range(127):
            blocks = data[508 + 2 * slot]
            if not blocks:
                continue
            selected = max(0, min(blocks * 254, len(data) - pos))
            items += 1
            work += 6 * selected
            output += 1536 + 4 * selected
            reason = budget_issue("CVT", work, output, items)
            if reason:
                return reason
            pos += blocks * 254
    return budget_issue("CVT", work, output, items)
