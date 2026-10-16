"""Run explicitly selected local unittest sources and save validation evidence.

Use ``python -m deadbits.validation.unittests --help`` for the standalone entry
point. This does not change the recovery CLI or require tests in an installation.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback
import unittest

from deadbits.validation.model import (
    Artifact, Context, Dataset, Environment, Resource, TestEvidence,
    ValidationEvidence,
)
from deadbits.version import VERSION


_STACK = "DEADBITS_UNITTEST_SELECTIONS"
_BOOTSTRAP = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
              "from deadbits.validation.unittests import _worker; "
              "_worker(*sys.argv[1:])")
_OUTCOMES = ("passed", "failed", "errors", "skipped", "expected_failures",
             "unexpected_successes")
_PRIORITY = dict(zip(_OUTCOMES, (0, 4, 5, 2, 1, 3)))
_SOURCE_HELP = ("Source tests are unavailable. Portable installations do not "
                "include the source suite. Supply --source-kit PATH to an "
                "extracted source checkout, or --tests-dir PATH explicitly.")


class _AccountingResult(unittest.TextTestResult):
    """Keep one outcome per executed parent, plus explicit fixture events."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self._current = None
        self._outcome = None

    def startTest(self, test):
        super().startTest(test)
        self._current = test
        self._outcome = None

    def _record(self, test, outcome):
        if test is self._current:
            if self._outcome is None or _PRIORITY[outcome] > _PRIORITY[self._outcome]:
                self._outcome = outcome
        else:
            # setUpClass/setUpModule/tearDownClass errors and fixture skips do
            # not receive startTest/stopTest and must not vanish from evidence.
            self.cases.append(dict(id=test.id(), outcome=outcome, kind="fixture"))

    def stopTest(self, test):
        self.cases.append(dict(id=test.id(), outcome=self._outcome or "errors",
                               kind="test"))
        self._current = None
        self._outcome = None
        super().stopTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed")

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "errors")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(self._current if self._current is not None else test, "skipped")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "expected_failures")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "unexpected_successes")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(test, "failed" if issubclass(err[0], test.failureException)
                         else "errors")


def _write_json(path, document):
    path.write_text(json.dumps(document, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _worker(tests_dir, pattern, result_path):
    """Internal child entry point; unittest tracebacks/output go to the log."""
    sys.path.insert(1, str(Path(tests_dir).parent))
    loader = unittest.TestLoader()
    summary = dict(discovered=None, run=None, fixture_events=0, cases=[],
                   counts=None, problem=None)
    try:
        suite = loader.discover(tests_dir, pattern=pattern)
        summary["discovered"] = suite.countTestCases()
        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2,
                                        resultclass=_AccountingResult).run(suite)
        summary.update(run=result.testsRun, cases=result.cases,
                       fixture_events=sum(c["kind"] == "fixture" for c in result.cases))
        counts = Counter(c["outcome"] for c in result.cases)
        summary["counts"] = {name: counts[name] for name in _OUTCOMES}
        if loader.errors:
            # _FailedTest normally accounts for these as errors. Preserve the
            # discovery problem too, including custom load_tests implementations.
            summary["problem"] = "Test discovery/import errors; see tests.log."
            for error in loader.errors:
                print(error, file=sys.stderr)
    except BaseException:
        # Import-time SystemExit/KeyboardInterrupt and broken load_tests hooks
        # are incomplete measurements, never a green partial run.
        traceback.print_exc()
        summary["problem"] = "Discovery or execution did not complete; see tests.log."
    _write_json(Path(result_path), summary)


def run_tests(*, output_dir, tests_dir=None, source_kit=None, pattern="test_*.py",
              timeout=300, commit=None):
    """Return schema-1 evidence, saving evidence.json, summary.json and tests.log.

    ``source_kit`` selects its ``tests/`` child; ``tests_dir`` selects a directory
    directly. Never infer sources from the CWD or installed application. Selected
    tests execute trusted local Python in a subprocess, without a shell.
    """
    if tests_dir is not None and source_kit is not None:
        raise ValueError("choose tests_dir or source_kit, not both")
    if not isinstance(pattern, str) or not pattern or "/" in pattern or "\\" in pattern:
        raise ValueError("pattern must be a nonempty filename glob")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout < float("inf"):
        raise ValueError("timeout must be a positive finite number of seconds")
    selected = (Path(source_kit) / "tests" if source_kit is not None else
                Path(tests_dir) if tests_dir is not None else None)
    selected = selected.resolve() if selected is not None else None
    destination = Path(output_dir).resolve()
    if selected is not None and (destination == selected or selected in destination.parents):
        raise ValueError("output_dir must be outside the selected test sources")
    destination.mkdir(parents=True, exist_ok=True)
    summary = dict(discovered=None, run=None, fixture_events=0, cases=[],
                   counts=None, problem=None)
    log_path = destination / "tests.log"
    # No stale passing results can survive a failed new worker invocation.
    for name in ("evidence.json", "summary.json"):
        (destination / name).unlink(missing_ok=True)
    problem = None
    if selected is None or not selected.is_dir():
        problem = _SOURCE_HELP
    try:
        stack = json.loads(os.environ.get(_STACK, "[]"))
        if not isinstance(stack, list) or any(not isinstance(p, str) for p in stack):
            raise ValueError("invalid runner selection stack")
    except (ValueError, TypeError):
        stack = []
        problem = "Invalid test-runner recursion guard."
    key = os.path.normcase(str(selected))
    if key in stack or len(stack) >= 8:
        problem = "Recursive execution of the selected test suite was refused."
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        if problem:
            log.write(problem + "\n")
        else:
            env = os.environ.copy()
            env[_STACK] = json.dumps(stack + [key])
            env["PYTHONIOENCODING"] = "utf-8"
            with tempfile.TemporaryDirectory(prefix="deadbits-unittest-") as temp:
                result_path = Path(temp) / "result.json"
                # Same-size edits within a timestamp tick can leave a valid-looking
                # stale .pyc. A fresh prefix also bypasses existing source caches.
                env["PYTHONPYCACHEPREFIX"] = str(Path(temp) / "pycache")
                # The import root may be a checkout directory OR an installed
                # .pyz archive. Do not treat __file__ inside a zip as a script.
                command = [sys.executable, "-c", _BOOTSTRAP,
                           str(Path(__file__).resolve().parents[2]),
                           str(selected), pattern, str(result_path)]
                try:
                    process = subprocess.run(command, cwd=str(selected.parent), env=env,
                                             stdout=log, stderr=log, timeout=timeout,
                                             check=False)
                    if process.returncode != 0:
                        problem = "Test worker exited with code %s; see tests.log." % process.returncode
                    elif not result_path.is_file():
                        problem = "Test worker produced no result; see tests.log."
                    else:
                        summary = json.loads(result_path.read_text(encoding="utf-8"))
                        problem = summary["problem"]
                except subprocess.TimeoutExpired:
                    problem = "Test worker timed out after %s seconds; see tests.log." % timeout
                except (OSError, ValueError):
                    traceback.print_exc(file=log)
                    problem = "Test worker could not complete; see tests.log."
            if problem:
                log.write("\n" + problem + "\n")
    if not problem and summary["discovered"] == 0:
        problem = "No tests were discovered for pattern %r." % pattern
    if not problem and summary["counts"] and sum(summary["counts"].values()) == summary["counts"]["skipped"]:
        problem = "All test outcomes were skipped; no executed checks are available."
    if problem:
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write("\nValidation unavailable: " + problem + "\n")
    summary.update(problem=problem, tests_dir=str(selected) if selected else None,
                   pattern=pattern)
    _write_json(destination / "summary.json", summary)
    artifacts = tuple(Artifact(role, name, hashlib.sha256((destination / name).read_bytes()).hexdigest())
                      for role, name in (("test_summary", "summary.json"), ("test_log", "tests.log")))
    context = Context(app_version=VERSION, commit=commit,
                      dataset=Dataset(identity="%s (%s)" % (selected, pattern)) if selected else Dataset(),
                      environment=Environment(platform.python_version(), platform.platform()),
                      provenance="live", recorded_at=datetime.now(timezone.utc).isoformat(),
                      source=str(selected) if selected else None)
    evidence = ValidationEvidence(tests=TestEvidence(
        context=context, resources=(Resource("source test suite", problem is None, problem),),
        artifacts=artifacts, **(summary["counts"] or {})))
    _write_json(destination / "evidence.json", evidence.to_dict())
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run selected source tests and save validation evidence.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--tests-dir", help="explicit local unittest discovery directory")
    selection.add_argument("--source-kit", help="source checkout containing tests/ (not a portable install)")
    parser.add_argument("--output-dir", required=True, help="directory for evidence.json, summary.json, tests.log")
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--timeout", type=float, default=300, help="worker timeout in seconds (default: 300)")
    parser.add_argument("-v", "--verbose", action="store_true", help="also print the detailed unittest log")
    args = parser.parse_args(argv)
    try:
        evidence = run_tests(output_dir=args.output_dir, tests_dir=args.tests_dir,
                             source_kit=args.source_kit, pattern=args.pattern, timeout=args.timeout)
    except (OSError, ValueError) as error:
        parser.exit(2, "Test runner: %s\n" % error)
    output = Path(args.output_dir)
    if args.verbose:
        print((output / "tests.log").read_text(encoding="utf-8", errors="replace"), end="")
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    tests = evidence.tests
    def count(value):
        return "unknown" if value is None else str(value)
    print("Tests %s: discovered=%s run=%s %s" % (
        tests.status, count(summary["discovered"]), count(summary["run"]),
        " ".join("%s=%s" % (name, count(getattr(tests, name))) for name in _OUTCOMES)))
    if summary["fixture_events"]:
        print("Additional fixture events: %s" % summary["fixture_events"])
    if summary["problem"]:
        print(summary["problem"])
    print("Evidence: %s" % (output / "evidence.json").resolve())
    return 0 if tests.status == "passed" else 1 if tests.status == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
