"""CLI modes preserve recovery, distinguish missing proof and render saved truth."""
import contextlib
import dataclasses
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from deadbits import cli, diagnostics, presentation
from deadbits.validation.model import (Artifact, BenchmarkEvidence, Context, Dataset,
    Environment, ReferenceEvidence, Resource, TestEvidence, ValidationEvidence)

ROOT = Path(__file__).resolve().parent.parent


def invoke(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


class Modes(unittest.TestCase):
    def test_recovery_with_unicode_paths_and_verbose_keeps_json_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            src, dst = Path(temp) / 'entrée files', Path(temp) / 'out files'
            src.mkdir()
            (src / 'sample.dat').write_bytes(b'not recognized')
            code, out, err = invoke([str(src), str(dst), '--verbose'])
            self.assertEqual(code, 0, err)
            self.assertIn('Accuracy unavailable', out)
            self.assertIn('sample.dat', out)
            self.assertNotIn('\x1b', out)
            report = json.loads((dst / 'report.json').read_text())
            self.assertEqual(set(report), {'tool_version', 'files', 'totals'})
            self.assertEqual(set(report['files'][0]), {'file', 'format', 'status', 'records', 'damage'})
            self.assertEqual(set(json.loads((dst / 'sample.dat.json').read_text())),
                             {'source_file', 'format', 'status', 'metadata', 'records', 'damage'})

    def test_usage_exit_codes(self):
        for args, expected in [([], 0), (['one'], 0), (['--wat'], 0),
                (['--verify', '--test'], 2), (['--test', '--wat'], 2),
                (['--verify=true'], 2), (['--doctor=false'], 2),
                (['--doctor', 'input', 'output'], 2),
                (['--doctor', '--evidence-dir', 'output'], 2),
                (['--verify', '--evidence-file', 'saved', '--kit-dir', 'kit'], 2),
                (['--verify', '--evidence-file'], 2), (['--help'], 0), (['--version'], 0)]:
            with self.subTest(args=args):
                self.assertEqual(invoke(args)[0], expected)

    def test_missing_runners_are_unavailable_and_never_write(self):
        for mode, module in diagnostics.RUNNERS.items():
            name = 'deadbits.validation.' + module
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'new'
                with mock.patch.object(diagnostics.importlib, 'import_module',
                        side_effect=ModuleNotFoundError(name=name)):
                    code, out, _ = invoke(['--' + mode, '--evidence-dir', str(target)])
                self.assertEqual(code, 3)
                self.assertIn('unavailable', out)
                self.assertFalse(target.exists())
                # Existing evidence must also remain untouched on missing runners.
                target.mkdir()
                (target / 'validation.json').write_text('original')
                with mock.patch.object(diagnostics.importlib, 'import_module',
                        side_effect=ModuleNotFoundError(name=name)):
                    self.assertEqual(invoke(['--' + mode, '--evidence-dir', str(target)])[0], 3)
                self.assertEqual((target / 'validation.json').read_text(), 'original')

    def test_doctor_is_read_only_and_shows_missing_explicit_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'not installed'
            code, out, _ = invoke(['--doctor', '--source-dir', str(missing), '--kit-dir', str(missing)])
            self.assertEqual(code, 3)
            self.assertIn('3.12' if sys.version_info[:2] == (3, 12) else 'Python', out)
            self.assertIn('BRAVO', out)
            self.assertIn('Missing or empty', out)
            self.assertFalse(missing.exists())

    def test_doctor_missing_adapter_is_failure(self):
        with mock.patch.object(diagnostics, 'ADAPTERS', []):
            self.assertEqual(invoke(['--doctor'])[0], 1)

    def test_doctor_complete_presence_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder, name in [('tests', 'test_example.py'), ('samples', 'sample.dat'),
                                 ('expected_outputs', 'sample.json')]:
                (root / folder).mkdir()
                (root / folder / name).write_text('fixture')
            (root / 'tools').mkdir()
            for name in ('evaluate.py', 'make_variants.py'):
                (root / 'tools' / name).write_text('# presence fixture')
            with mock.patch.object(diagnostics.importlib, 'import_module',
                                   return_value=types.SimpleNamespace(run=lambda request: None)):
                self.assertEqual(invoke(['--doctor', '--source-dir', str(root), '--kit-dir', str(root)])[0], 0)

    def test_historical_saved_sections_and_artifact_paths(self):
        original = Context(app_version='old-version', commit='old-commit', provenance='live',
                           environment=Environment('3.10.1', 'old platform'))
        evidence = ValidationEvidence(reference=ReferenceEvidence(context=original, matched=2, total=2,
            artifacts=(Artifact('actual', 'actual/sample.json'),)), tests=TestEvidence(failed=1))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'preuve é.json'
            path.write_text(json.dumps(evidence.to_dict()))
            before = path.read_bytes()
            code, out, _ = invoke(['--verify', '--evidence-file', str(path), '--verbose'])
            self.assertEqual(code, 0)
            self.assertIn('2/2 (100.0%)', out)
            self.assertIn('historical', out)
            self.assertIn('old-version', out)
            self.assertIn('3.10.1', out)
            # Windows temporary roots may use an 8.3 alias; CLI resolves the evidence path.
            self.assertIn(str(path.resolve().parent / 'actual/sample.json'), out)
            self.assertNotIn('Tests:', out)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(invoke(['--test', '--evidence-file', str(path)])[0], 1)
            self.assertEqual(invoke(['--benchmark', '--evidence-file', str(path)])[0], 3)

    def test_bad_saved_evidence_and_empty_counts_never_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'evidence.json'
            for contents in ('{', '{"schema_version": 99}',
                    json.dumps(ValidationEvidence(reference=ReferenceEvidence(matched=0, total=0)).to_dict())):
                path.write_text(contents)
                self.assertIn(invoke(['--verify', '--evidence-file', str(path)])[0], (1, 3))

    def test_selected_live_runner_receives_resolved_paths_and_saves_envelope(self):
        for mode, evidence in [('verify', ValidationEvidence(reference=ReferenceEvidence(matched=1, total=1))),
                ('test', ValidationEvidence(tests=TestEvidence(passed=1, failed=0, errors=0, skipped=0,
                    expected_failures=0, unexpected_successes=0))),
                ('benchmark', ValidationEvidence(benchmarks=(BenchmarkEvidence(cases=1, crashes=0),)))]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'preuve space é'
                runner = mock.Mock(return_value=evidence)
                with mock.patch.object(diagnostics.importlib, 'import_module',
                                       return_value=types.SimpleNamespace(run=runner)):
                    code, out, err = invoke(['--' + mode, '--evidence-dir', str(target)])
                self.assertEqual(code, 0, err)
                request = runner.call_args.args[0]
                self.assertEqual(request.evidence_dir, target.resolve())
                self.assertEqual(json.loads((target / 'validation.json').read_text()), evidence.to_dict())
                self.assertNotIn('\x1b', out)

    def test_runner_cannot_overwrite_inputs_or_prior_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / 'kit'
            protected.mkdir()
            marker = protected / 'report.json'
            marker.write_text('untouched')
            runner = mock.Mock(return_value=ValidationEvidence(reference=ReferenceEvidence(matched=1, total=1)))
            with mock.patch.object(diagnostics.importlib, 'import_module',
                                   return_value=types.SimpleNamespace(run=runner)):
                for target in (protected, protected / 'inside', root):
                    code, _, _ = invoke(['--verify', '--samples-dir', str(protected), '--evidence-dir', str(target)])
                    self.assertEqual(code, 1)
                # Existing unrelated directories are refused too.
                prior = root / 'prior'
                prior.mkdir()
                self.assertEqual(invoke(['--verify', '--evidence-dir', str(prior)])[0], 1)
            runner.assert_not_called()
            self.assertEqual(marker.read_text(), 'untouched')

    def test_symlink_alias_cannot_bypass_protected_kit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            samples, alias = root / 'samples', root / 'alias'
            samples.mkdir()
            try:
                alias.symlink_to(samples, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable')
            runner = mock.Mock()
            with mock.patch.object(diagnostics.importlib, 'import_module',
                                   return_value=types.SimpleNamespace(run=runner)):
                self.assertEqual(invoke(['--verify', '--samples-dir', str(samples),
                                         '--evidence-dir', str(alias / 'proof')])[0], 1)
            runner.assert_not_called()
            self.assertFalse((samples / 'proof').exists())

    def test_runner_failure_and_reserved_envelope_never_look_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            for case in ('exception', 'reserved'):
                target = Path(temp) / case
                def runner(request):
                    if case == 'exception':
                        raise RuntimeError('runner failed')
                    (request.evidence_dir / 'validation.json').write_text('runner artifact')
                    return ValidationEvidence(reference=ReferenceEvidence(matched=1, total=1))
                with mock.patch.object(diagnostics.importlib, 'import_module',
                                       return_value=types.SimpleNamespace(run=runner)):
                    code, out, err = invoke(['--verify', '--evidence-dir', str(target)])
                self.assertEqual(code, 1)
                self.assertNotIn('Validation: complete', out)
                self.assertIn('validation error', err)
                if case == 'reserved':
                    self.assertEqual((target / 'validation.json').read_text(), 'runner artifact')

    def test_broken_runner_dependency_and_invalid_result_fail(self):
        with mock.patch.object(diagnostics.importlib, 'import_module',
                               side_effect=ModuleNotFoundError(name='broken_dependency')):
            self.assertEqual(invoke(['--verify'])[0], 1)
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(diagnostics.importlib, 'import_module',
                                   return_value=types.SimpleNamespace(run=lambda request: ValidationEvidence())):
                self.assertEqual(invoke(['--verify', '--evidence-dir', str(Path(temp)/'new')])[0], 1)

    def test_presenter_keeps_baselines_denominators_and_unknowns_separate(self):
        evidence = ValidationEvidence(benchmarks=(
            BenchmarkEvidence(baseline='organizer_reference', cases=1, crashes=0, expected_records=2,
                              recovered_records=1, complete_records=1, false_verified_records=0),
            BenchmarkEvidence(baseline='regression_baseline', cases=1, crashes=0),
            BenchmarkEvidence(cases=1, crashes=0)))
        text = presentation.validation(evidence)
        self.assertIn('organizer_reference', text)
        self.assertIn('regression_baseline', text)
        self.assertIn('1/2 (50.0%)', text)
        self.assertIn('0/unavailable (unavailable)', text)
        self.assertIn('not independent accuracy', text)
        self.assertNotIn('\\x0a', text)

    def test_test_outcomes_are_not_rendered_as_recovery_accuracy(self):
        text = presentation.validation(ValidationEvidence(tests=TestEvidence(
            passed=3, failed=0, errors=0, skipped=1, expected_failures=1, unexpected_successes=0)))
        self.assertIn('expected failures', text)
        self.assertNotIn('%', text)

    def test_terminal_controls_and_limited_encoding(self):
        text = presentation.validation(ValidationEvidence(reference=ReferenceEvidence(
            resources=(Resource('bad\x1b[31m', False, 'line\nforged'),))))
        self.assertNotIn('\x1b', text)
        self.assertIn('\\x1b', text)
        self.assertIn('line\\x0aforged', text)
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='ascii')
        presentation.emit('preuve é', stream)
        stream.flush()
        self.assertIn(b'\\xe9', raw.getvalue())

    def test_portable_runs_outside_checkout_without_resources(self):
        # Build an application directly from runtime files, without Git or source tests.
        import zipfile
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / 'salvage.pyz'
            with zipfile.ZipFile(app, 'w') as archive:
                archive.writestr('__main__.py', 'from deadbits.cli import main\nraise SystemExit(main())\n')
                for path in (ROOT / 'deadbits').rglob('*.py'):
                    archive.write(path, str(path.relative_to(ROOT)).replace('\\', '/'))
            result = subprocess.run([sys.executable, str(app), '--doctor'], cwd=temp,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn('Format adapters', result.stdout)
            self.assertIn('Missing or empty', result.stdout)
            self.assertNotIn('\x1b', result.stdout)


class LiveServiceIntegration(unittest.TestCase):
    """Exercise the shared CLI against real runners and tiny trusted local kits."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source kit é & literal $name'
        self.tests = self.source / 'tests'
        self.tests.mkdir(parents=True)

    def suite(self, code):
        (self.tests / 'test_selected.py').write_text(code, encoding='utf-8')

    def run_suite(self, name='proof', verbose=False, source=None):
        output = self.root / name
        args = ['--test', '--source-dir', str(source or self.source), '--evidence-dir', str(output)]
        if verbose:
            args.append('--verbose')
        code, text, err = invoke(args)
        evidence = json.loads((output / 'validation.json').read_text(encoding='utf-8'))
        return code, text, err, output, ValidationEvidence.from_dict(evidence)

    def test_passing_selected_suite_preserves_counts_artifacts_and_verbose_provenance(self):
        self.suite('''import unittest
class Selected(unittest.TestCase):
    def test_ok(self): print('detail marker é')
    @unittest.skip('intentional skip')
    def test_skip(self): pass
    @unittest.expectedFailure
    def test_expected(self): self.fail('expected failure')
''')
        for verbose in (False, True):
            code, text, err, output, evidence = self.run_suite('verbose' if verbose else 'concise', verbose)
            self.assertEqual(code, 0, err)
            self.assertEqual(evidence.status, 'complete')
            item = evidence.tests
            self.assertEqual((item.passed, item.skipped, item.expected_failures, item.total), (1, 1, 1, 3))
            self.assertEqual(item.context.provenance, 'live')
            self.assertIn('Tests: passed', text)
            self.assertNotIn('%', text)
            self.assertNotIn('\x1b', text)
            self.assertIn(str(output / 'tests.log'), text)
            self.assertNotIn('detail marker', text)  # Full test output is saved in the linked log.
            self.assertEqual('Version:' in text, verbose)
            self.assertIn('detail marker é', (output / 'tests.log').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((output / 'evidence.json').read_text()), evidence.to_dict())
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual((summary['discovered'], summary['run']), (3, 3))

    def test_failed_error_and_unexpected_success_counts_survive_historical_display(self):
        self.suite('''import unittest
class Selected(unittest.TestCase):
    def test_fail(self): self.fail('intentional assertion')
    def test_error(self): raise RuntimeError('intentional exception')
    @unittest.expectedFailure
    def test_unexpected(self): pass
''')
        code, text, err, output, evidence = self.run_suite()
        self.assertEqual(code, 1, err)
        self.assertEqual((evidence.tests.failed, evidence.tests.errors, evidence.tests.unexpected_successes), (1, 1, 1))
        self.assertIn('Tests: failed', text)
        before = (output / 'validation.json').read_bytes()
        code, saved, err = invoke(['--test', '--evidence-file', str(output / 'validation.json'), '--verbose'])
        self.assertEqual(code, 1, err)
        self.assertIn('historical', saved)
        self.assertEqual((output / 'validation.json').read_bytes(), before)
        self.assertIn('intentional assertion', (output / 'tests.log').read_text())

    def test_empty_skipped_import_error_and_missing_suites_are_unavailable(self):
        scenarios = [('empty', None), ('skip', "import unittest\n@unittest.skip('skip')\nclass C(unittest.TestCase):\n def test_skip(self): pass\n"),
                     ('import', "raise RuntimeError('cannot import selected suite')\n"), ('missing', None)]
        for name, source in scenarios:
            with self.subTest(name=name):
                if source is not None:
                    self.suite(source)
                code, text, err, output, evidence = self.run_suite(name,
                    source=self.root / 'missing source' if name == 'missing' else self.source)
                self.assertEqual(code, 3, err)
                self.assertEqual(evidence.status, 'unavailable')
                self.assertNotIn('Tests: passed', text)
                if name == 'missing':
                    self.assertIn('--source-dir', text)
                self.assertTrue((output / 'tests.log').is_file())

    def test_test_mode_refuses_existing_recovery_output_and_source_descendants(self):
        self.suite('raise RuntimeError("must not execute")\n')
        output = self.root / 'recovery output'
        output.mkdir()
        report = output / 'report.json'
        report.write_text('original recovery report')
        for destination in (output, self.source / 'proof', self.tests / 'proof'):
            code, text, err = invoke(['--test', '--source-dir', str(self.source), '--evidence-dir', str(destination)])
            self.assertEqual(code, 1)
            self.assertNotIn('must not execute', err)
        self.assertEqual(report.read_text(), 'original recovery report')
        self.assertFalse((self.source / 'proof').exists())
        self.assertFalse((self.tests / 'proof').exists())

    def test_doctor_finds_real_runners_without_executing_tests_and_checks_scorers(self):
        from deadbits.validation import unittests
        self.suite('raise RuntimeError("doctor must not execute tests")\n')
        with mock.patch.object(unittests, 'run_tests', side_effect=AssertionError('executed')) as runner:
            code, text, err = invoke(['--doctor'])
            self.assertEqual(code, 0, err)
            self.assertIn('test runner', text)
            self.assertIn('benchmark scoring tools', text)
            code, text, err = invoke(['--doctor', '--source-dir', str(self.source),
                                     '--kit-dir', str(ROOT / 'samples/official')])
            self.assertEqual(code, 3, err)
            self.assertIn('Missing evaluate.py/make_variants.py', text)
            runner.assert_not_called()

    def test_reference_and_benchmark_modes_use_real_services_and_separate_evidence(self):
        samples, expected = self.root / 'samples', self.root / 'expected'
        samples.mkdir()
        expected.mkdir()
        (samples / 'unknown.dat').write_bytes(b'unknown binary content\0')
        (expected / 'answer.json').write_text(json.dumps(dict(file='unknown.dat', format='UNKNOWN',
                                                              status='unrecognized', records=[])))
        for mode in ('verify', 'benchmark'):
            output = self.root / mode
            code, text, err = invoke(['--' + mode, '--source-dir', str(ROOT), '--samples-dir', str(samples),
                                     '--expected-dir', str(expected), '--evidence-dir', str(output)])
            self.assertEqual(code, 0, err)
            evidence = ValidationEvidence.from_dict(json.loads((output / 'validation.json').read_text()))
            self.assertIsNone(evidence.tests)
            self.assertNotIn('\x1b', text)
            if mode == 'verify':
                self.assertEqual((evidence.reference.matched, evidence.reference.total), (1, 1))
                self.assertEqual(evidence.benchmarks, ())
            else:
                self.assertIsNone(evidence.reference)
                self.assertTrue(evidence.benchmarks)
                # A supplied organizer answer remains independent truth, even with zero records.
                self.assertIn('organizer_reference', text)
                self.assertTrue(all(row.measurements['recovery'].value is None for row in evidence.benchmarks))

    def test_portable_test_mode_uses_explicit_external_kit_and_reports_missing_sources(self):
        import zipfile
        self.suite('import unittest\nclass C(unittest.TestCase):\n def test_ok(self): pass\n')
        app = self.root / 'salvage.pyz'
        with zipfile.ZipFile(app, 'w') as archive:
            archive.writestr('__main__.py', 'from deadbits.cli import main\nraise SystemExit(main())\n')
            for path in (ROOT / 'deadbits').rglob('*.py'):
                archive.write(path, path.relative_to(ROOT).as_posix())
        for name, selection, expected in [('missing', [], 3), ('selected', ['--source-dir', str(self.source)], 0)]:
            output = self.root / ('portable ' + name)
            result = subprocess.run([sys.executable, str(app), '--test', *selection,
                                     '--evidence-dir', str(output)], cwd=self.root,
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertNotIn('\x1b', result.stdout)
            evidence = ValidationEvidence.from_dict(json.loads((output / 'validation.json').read_text()))
            if name == 'missing':
                self.assertIn('--source-dir', result.stdout)
                self.assertIsNone(evidence.tests.total)
            else:
                self.assertEqual((evidence.tests.passed, evidence.tests.total), (1, 1))
                self.assertIn(str(output / 'tests.log'), result.stdout)
