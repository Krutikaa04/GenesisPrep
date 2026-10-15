"""Shared test helpers (official kit lives in samples/official)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

KIT = ROOT / "samples" / "official"
SAMPLES = KIT / "samples"
EXPECTED = KIT / "expected_outputs"

from deadbits.engine import salvage_bytes  # noqa: E402
from deadbits.model import FORMAT_NAMES, KINDS, STATUSES  # noqa: E402


def sample_files():
    return sorted(p for p in SAMPLES.iterdir() if p.is_file())


def check_contract(testcase, res, size=None, label=""):
    """Every result must be a valid contract document, whatever the input was."""
    doc = res.to_dict()
    testcase.assertIn(doc["status"], STATUSES, label)
    testcase.assertIn(doc["format"], FORMAT_NAMES, label)
    testcase.assertIsInstance(doc["metadata"], dict, label)
    testcase.assertIsInstance(doc["records"], list, label)
    for d in doc["damage"]:
        testcase.assertIn(d["kind"], KINDS, label)
        testcase.assertIsInstance(d["offset"], int, label)
        testcase.assertIsInstance(d["lossy"], bool, label)
        testcase.assertGreaterEqual(d["offset"], 0, label)
        if size is not None:
            testcase.assertLessEqual(d["offset"], size, label)
    testcase.assertFalse([n for n in res.notes if "decoder exception" in n], "%s: %s" % (label, res.notes))
    return doc
