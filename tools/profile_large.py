"""Development-only deterministic large-input timing/allocation measurements."""
import hashlib
import json
import platform
from pathlib import Path
import time
import tracemalloc

from deadbits.engine import salvage_bytes


def profile(cases):
    rows = []
    for name, data in cases:
        tracemalloc.start()
        started = time.perf_counter()
        result = salvage_bytes(data, name)
        encoded = json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
        elapsed = (time.perf_counter() - started) * 1000
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        rows.append(dict(case=name, input_bytes=len(data), input_sha256=hashlib.sha256(data).hexdigest(),
                         format=result.format, status=result.status, records=len(result.records),
                         damage=result.damage, json_bytes=len(encoded), elapsed_ms=round(elapsed, 3),
                         peak_traced_bytes=peak))
    root = Path(__file__).resolve().parent.parent / "deadbits"
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(root.glob("_large*.py")) + [root / "_limits.py"]}
    return dict(schema_version=1, python=platform.python_version(), platform=platform.platform(),
                policy_sources_sha256=sources,
                method="One traced parsing+JSON run per case; fixture/input allocation excluded; not process RSS or a timing guarantee.",
                rows=rows)
