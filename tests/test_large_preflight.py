"""The optional large-input extension always defaults to the existing refusal."""
import unittest
from unittest.mock import patch

from helpers import check_contract
from deadbits import _large


class LargePreflight(unittest.TestCase):
    def test_absent_broken_unknown_and_invalid_helpers_keep_refusal(self):
        for failure in (ModuleNotFoundError(), RuntimeError(), SyntaxError()):
            with patch.object(_large.importlib, "import_module", side_effect=failure):
                self.assertEqual(_large.resource_issue(b"x", "CVT", "coarse"), "coarse")
        self.assertEqual(_large.resource_issue(b"x", "UNKNOWN", "coarse"), "coarse")
        with patch.object(_large.importlib, "import_module") as module:
            module.return_value.resource_issue.return_value = False
            self.assertEqual(_large.resource_issue(b"x", "CVT", "coarse"), "coarse")
            module.return_value.resource_issue.side_effect = ValueError()
            self.assertIn("safe bound", _large.resource_issue(b"x", "CVT", "coarse"))

    def test_limits_are_inclusive_and_independent(self):
        for field, ceiling in (("work", _large.MAX_WORK_BYTES), ("output", _large.MAX_OUTPUT_BYTES),
                               ("items", _large.MAX_ITEMS)):
            counts = dict(work=0, output=0, items=0)
            counts[field] = ceiling
            self.assertIsNone(_large.budget_issue("TEST", **counts))
            counts[field] += 1
            self.assertIn("budget", _large.budget_issue("TEST", **counts))
