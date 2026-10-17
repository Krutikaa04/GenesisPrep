"""Selective large-input preflights; missing/failed checks retain coarse refusal.

Only trusted local, explicitly named helpers can extend an existing refusal.
Small-input behavior stays with the existing adapters and limits. Every helper
must establish bounded framing/work/output before allowing the normal decoder.
Logical output charges are not process-RSS or exact serialized JSON promises.
"""
import importlib

MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_WORK_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_ITEMS = 100_000

_MODULES = {"CVT": "cvt", "LIBRA-98": "libra", "LABLOG": "lablog",
            "WKS": "wks", "EBCDIC-DUMP": "ebcdic"}


def resource_issue(data, fmt, coarse_reason):
    if len(data) > MAX_SCAN_BYTES:
        return coarse_reason + "; selective large-input scan safety limit is %d bytes" % MAX_SCAN_BYTES
    suffix = _MODULES.get(fmt)
    if suffix is None:
        return coarse_reason
    try:
        module = importlib.import_module("._large_" + suffix, __package__)
    except Exception:
        return coarse_reason  # absent/broken helpers never authorize decoding
    try:
        reason = module.resource_issue(data, coarse_reason)
    except Exception:
        return coarse_reason + "; large-input preflight could not establish a safe bound"
    return reason if reason is None or isinstance(reason, str) else coarse_reason


def budget_issue(fmt, work, output, items):
    for value, ceiling, name in ((items, MAX_ITEMS, "item"), (work, MAX_WORK_BYTES, "work"),
                                 (output, MAX_OUTPUT_BYTES, "output")):
        if value > ceiling:
            return "%s projected %s exceeds the %d-unit safety budget" % (fmt, name, ceiling)
    return None
