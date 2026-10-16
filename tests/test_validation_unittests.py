"""Known-answer synthetic suites for the source-test runner and its CLI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import zipfile

from deadbits.validation.model import ValidationEvidence
from deadbits.validation.unittests import run_tests


class UnittestRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "source kit & literal $name" / "tests"
        self.sources.mkdir(parents=True)
        self.output = self.root / "evidence"

    def write_suite(self, source, name="test_cases.py"):
        (self.sources / name).write_text(textwrap.dedent(source), encoding="utf-8")

    def run_suite(self, **kwargs):
        return run_tests(tests_dir=self.sources, output_dir=self.output, **kwargs).tests

    def summary(self):
        return json.loads((self.output / "summary.json").read_text(encoding="utf-8"))

    def test_all_outcomes_are_dynamic_and_round_trip_with_logs(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_pass(self):
                    print("captured stdout")
                def test_fail(self): self.fail("known failure")
                def test_error(self): raise RuntimeError("known error")
                @unittest.skip("known skip")
                def test_skip(self): pass
                @unittest.expectedFailure
                def test_expected(self): self.fail("expected")
                @unittest.expectedFailure
                def test_unexpected(self): pass
        ''')
        evidence = self.run_suite()
        self.assertEqual(evidence.status, "failed")
        for name in ("passed", "failed", "errors", "skipped", "expected_failures", "unexpected_successes"):
            self.assertEqual(getattr(evidence, name), 1, name)
        self.assertEqual(evidence.total, 6)
        self.assertEqual((self.summary()["discovered"], self.summary()["run"]), (6, 6))
        log = (self.output / "tests.log").read_text(encoding="utf-8")
        for message in ("known failure", "known error", "known skip", "unexpected success", "captured stdout"):
            self.assertIn(message, log)
        saved = ValidationEvidence.from_dict(json.loads((self.output / "evidence.json").read_text()))
        self.assertEqual(saved.tests, evidence)
        self.assertEqual(evidence.context.provenance, "live")
        self.assertIsNone(evidence.context.commit)
        self.assertIsNone(evidence.context.dataset.sha256)
        for artifact in evidence.artifacts:
            self.assertEqual(artifact.sha256, hashlib.sha256((self.output / artifact.path).read_bytes()).hexdigest())

    def test_multiple_subtests_collapse_to_one_parent_error(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_subtests(self):
                    for n in range(3):
                        with self.subTest(n=n): self.fail("failure")
                    with self.subTest(error=True): raise RuntimeError("subtest error")
                    with self.subTest(skip=True): self.skipTest("subtest skip")
        ''')
        result = self.run_suite()
        self.assertEqual((result.total, result.errors, result.failed, result.skipped), (1, 1, 0, 0))
        self.assertEqual(self.summary()["run"], 1)
        self.assertIn("subtest error", (self.output / "tests.log").read_text())

    def test_failed_and_skipped_subtests_do_not_become_passes(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_failed(self):
                    for i in range(3):
                        with self.subTest(i=i): self.fail("failure")
                def test_skipped(self):
                    with self.subTest(i=0): pass
                    with self.subTest(i=1): self.skipTest("partially skipped")
                def test_successful(self):
                    for i in range(3):
                        with self.subTest(i=i): pass
        ''')
        result = self.run_suite()
        self.assertEqual((result.total, result.failed, result.skipped, result.passed), (3, 1, 1, 1))

    def test_teardown_and_cleanup_errors_do_not_double_count_method(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_bad(self):
                    self.addCleanup(lambda: 1 / 0)
                    self.fail("method failure")
                def tearDown(self): raise RuntimeError("teardown error")
        ''')
        result = self.run_suite()
        self.assertEqual((result.total, result.errors, result.failed), (1, 1, 0))

    def test_class_fixture_failure_is_visible_without_counting_unrun_methods(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                @classmethod
                def setUpClass(cls): raise RuntimeError("class setup error")
                def test_one(self): pass
                def test_two(self): pass
        ''')
        result = self.run_suite()
        self.assertEqual(result.status, "failed")
        self.assertEqual((result.passed, result.errors), (0, 1))
        self.assertEqual((self.summary()["discovered"], self.summary()["run"],
                          self.summary()["fixture_events"]), (2, 0, 1))

    def test_module_fixture_skip_and_class_teardown_error(self):
        self.write_suite('''
            import unittest
            def setUpModule(): raise unittest.SkipTest("module unavailable")
            class Cases(unittest.TestCase):
                def test_one(self): pass
        ''', "test_skip.py")
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_one(self): pass
                @classmethod
                def tearDownClass(cls): raise RuntimeError("class teardown error")
        ''', "test_teardown.py")
        result = self.run_suite()
        self.assertEqual((result.passed, result.errors, result.skipped), (1, 1, 1))
        self.assertEqual((self.summary()["run"], self.summary()["fixture_events"]), (1, 2))

    def test_import_error_is_unavailable_with_error_count_and_traceback(self):
        self.write_suite("raise ImportError('missing local dependency')")
        result = self.run_suite()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.errors, 1)
        self.assertIn("discovery/import", self.summary()["problem"])
        self.assertIn("missing local dependency", (self.output / "tests.log").read_text())

    def test_broken_discovery_hook_and_import_time_exit_never_pass(self):
        for source in ("def load_tests(*args): raise RuntimeError('broken discovery')", "raise SystemExit(0)"):
            with self.subTest(source=source):
                self.write_suite(source)
                self.assertEqual(self.run_suite().status, "unavailable")

    def test_empty_and_skip_only_suites_are_unavailable(self):
        result = self.run_suite()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual((result.total, self.summary()["discovered"], self.summary()["run"]), (0, 0, 0))
        self.write_suite('''
            import unittest
            @unittest.skip("platform")
            class Cases(unittest.TestCase):
                def test_skip(self): pass
        ''')
        result = self.run_suite()
        self.assertEqual((result.status, result.skipped, result.passed), ("unavailable", 1, 0))

    def test_missing_source_or_no_explicit_selection_explains_source_kit(self):
        for selection in ({}, {"tests_dir": self.root / "missing"}, {"source_kit": self.root / "portable"}):
            with self.subTest(selection=selection):
                evidence = run_tests(output_dir=self.output, **selection)
                self.assertEqual(evidence.tests.status, "unavailable")
                self.assertIsNone(evidence.tests.passed)
                self.assertIsNone(self.summary()["discovered"])
                self.assertIn("--source-kit", evidence.tests.resources[0].detail)

    def test_explicit_source_kit_and_pattern_select_only_requested_tests(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_good(self): pass
        ''', "check_good.py")
        self.write_suite("raise RuntimeError('must not import')")
        result = run_tests(source_kit=self.sources.parent, pattern="check_*.py",
                           output_dir=self.output).tests
        self.assertEqual((result.status, result.passed, self.summary()["discovered"]), ("passed", 1, 1))

    def test_timeout_and_abrupt_exit_replace_previous_success_with_unknown(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_good(self): pass
        ''')
        self.assertEqual(self.run_suite().status, "passed")
        self.write_suite("import os; os._exit(0)")
        result = self.run_suite()
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.passed)
        self.assertIn("no result", self.summary()["problem"])
        self.write_suite("import time; time.sleep(10)")
        result = self.run_suite(timeout=0.5)
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.total)
        self.assertIn("timed out", self.summary()["problem"])

    def test_recursive_same_selection_is_refused(self):
        self.write_suite("raise RuntimeError('must never be executed')")
        selection = os.path.normcase(str(self.sources.resolve()))
        with patch.dict(os.environ, {"DEADBITS_UNITTEST_SELECTIONS": json.dumps([selection])}):
            result = self.run_suite()
        self.assertEqual(result.status, "unavailable")
        self.assertIn("Recursive execution", result.resources[0].detail)
        self.assertNotIn("must never be executed", (self.output / "tests.log").read_text())

    def test_nested_runner_cannot_execute_its_own_suite(self):
        self.write_suite('''
            from pathlib import Path
            import unittest
            from deadbits.validation.unittests import run_tests
            class Cases(unittest.TestCase):
                def test_recursive(self):
                    root = Path(__file__).parent
                    evidence = run_tests(tests_dir=root, output_dir=root.parent / "nested")
                    self.assertEqual(evidence.tests.status, "unavailable")
                    self.assertIn("Recursive execution", evidence.tests.resources[0].detail)
        ''')
        self.assertEqual(self.run_suite().status, "passed")

    def test_invalid_options_and_output_in_sources_rejected_before_execution(self):
        for options in ({"timeout": 0}, {"timeout": float("nan")},
                        {"timeout": True}, {"pattern": "../test_*.py"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_suite(**options)
        with self.assertRaises(ValueError):
            run_tests(tests_dir=self.sources, source_kit=self.sources.parent, output_dir=self.output)
        with self.assertRaises(ValueError):
            run_tests(tests_dir=self.sources, output_dir=self.sources / "evidence")

    def test_portable_archive_without_tests_supports_explicit_source_kit(self):
        repo = Path(__file__).resolve().parents[1]
        archive = self.root / "portable app.pyz"
        names = ("deadbits/__init__.py", "deadbits/version.py",
                 "deadbits/validation/__init__.py", "deadbits/validation/model.py",
                 "deadbits/validation/unittests.py")
        with zipfile.ZipFile(archive, "w") as bundle:
            for name in names:
                bundle.write(repo / name, name)
        bootstrap = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                     "from deadbits.validation.unittests import main; "
                     "sys.exit(main())")
        command = [sys.executable, "-c", bootstrap, str(archive),
                   "--output-dir", str(self.output)]
        missing = subprocess.run(command, cwd=self.root, capture_output=True,
                                 text=True, encoding="utf-8", timeout=20)
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertIn("--source-kit", missing.stdout)
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_good(self): pass
        ''')
        selected = subprocess.run(command + ["--source-kit", str(self.sources.parent)],
                                  cwd=self.root, capture_output=True,
                                  text=True, encoding="utf-8", timeout=20)
        self.assertEqual(selected.returncode, 0, selected.stderr + selected.stdout)
        self.assertIn("passed=1", selected.stdout)

    def cli(self, *options):
        return subprocess.run([sys.executable, "-m", "deadbits.validation.unittests",
                               "--output-dir", str(self.output), *options],
                              cwd=Path(__file__).resolve().parents[1],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_existing_bytecode_cannot_hide_same_size_same_timestamp_source_edit(self):
        import py_compile
        passing = "import unittest\nclass Cases(unittest.TestCase):\n def test_current(self): pass\n"
        failing = "import unittest\nclass Cases(unittest.TestCase):\n def test_current(self): self.fail('fresh')\n"
        width = max(len(passing), len(failing))
        source = self.sources / "test_fresh.py"
        source.write_text(passing.ljust(width), encoding="utf-8")
        timestamp = source.stat()
        py_compile.compile(str(source), doraise=True)
        source.write_text(failing.ljust(width), encoding="utf-8")
        os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
        evidence = self.run_suite()
        self.assertEqual((evidence.status, evidence.failed, evidence.passed), ("failed", 1, 0))
        self.assertIn("fresh", (self.output / "tests.log").read_text(encoding="utf-8"))

    def test_cli_concise_verbose_and_exit_codes(self):
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_named(self): print("detail marker")
        ''')
        concise = self.cli("--tests-dir", str(self.sources))
        self.assertEqual(concise.returncode, 0, concise.stderr)
        self.assertIn("discovered=1 run=1 passed=1", concise.stdout)
        self.assertNotIn("detail marker", concise.stdout)
        verbose = self.cli("--source-kit", str(self.sources.parent), "--verbose")
        self.assertEqual(verbose.returncode, 0, verbose.stderr)
        self.assertIn("detail marker", verbose.stdout)
        self.assertIn("test_named", verbose.stdout)
        missing = self.cli()
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--source-kit", missing.stdout)
        self.write_suite('''
            import unittest
            class Cases(unittest.TestCase):
                def test_bad(self): self.fail("intentional")
        ''')
        failed = self.cli("--tests-dir", str(self.sources))
        self.assertEqual(failed.returncode, 1)
        self.assertIn("failed=1", failed.stdout)


if __name__ == "__main__":
    unittest.main()
