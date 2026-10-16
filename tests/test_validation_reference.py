"""Known-answer reference matching, saved evidence and protected-path behavior."""
import contextlib
import io
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from deadbits.diagnostics import ValidationRequest, run_validation
from deadbits.validation import reference
from deadbits.validation.model import ValidationEvidence

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / 'samples' / 'official'


class ReferenceRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.samples = self.root / 'samples é & $literal'
        self.expected = self.root / 'expected answers'
        self.output = self.root / 'evidence'
        self.samples.mkdir()
        self.expected.mkdir()
        self.document = dict(file='unknown.dat', format='UNKNOWN', status='unrecognized', records=[])
        (self.samples / 'unknown.dat').write_bytes(b'unknown binary input\0')
        self.write_reference()

    def write_reference(self, document=None, name='answer.json'):
        (self.expected / name).write_text(json.dumps(self.document if document is None else document),
                                          encoding='utf-8')

    def run_reference(self, **kwargs):
        return reference.run_references(samples_dir=self.samples, expected_dir=self.expected,
                                         output_dir=self.output, **kwargs)

    def test_live_known_answer_artifacts_hashes_and_snapshot_identity(self):
        before = {str(p): p.read_bytes() for root in (self.samples, self.expected) for p in root.iterdir()}
        envelope = self.run_reference()
        evidence = envelope.reference
        self.assertEqual(envelope.status, 'complete')
        self.assertEqual((evidence.matched, evidence.total), (1, 1))
        self.assertEqual(evidence.context.provenance, 'live')
        self.assertIsNone(evidence.context.commit)
        self.assertIn('+00:00', evidence.context.recorded_at)
        saved = ValidationEvidence.from_dict(json.loads((self.output/'reference-evidence.json').read_text()))
        self.assertEqual(saved, envelope)
        for artifact in evidence.artifacts:
            self.assertFalse(Path(artifact.path).is_absolute())
            self.assertEqual(hashlib.sha256((self.output/artifact.path).read_bytes()).hexdigest(), artifact.sha256)
        manifest = json.loads((self.output/'dataset-manifest.json').read_text())
        canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        self.assertEqual(evidence.context.dataset.sha256, hashlib.sha256(canonical).hexdigest())
        self.assertEqual({str(p): p.read_bytes() for root in (self.samples, self.expected)
                          for p in root.iterdir()}, before)
        case = json.loads((self.output/'comparison.json').read_text())['cases'][0]
        actual = json.loads((self.output/case['actual']).read_text())
        self.assertEqual(actual['source_file'], 'unknown.dat')
        self.assertEqual(set(actual), {'source_file', 'format', 'status', 'metadata', 'records', 'damage'})
        self.assertEqual((self.output/case['expected']).read_bytes(), (self.expected/'answer.json').read_bytes())
        self.assertFalse((self.output/'report.json').exists())

    def test_mismatch_saves_exact_actual_and_detailed_expected_actual_values(self):
        self.document.update(status='ok', metadata={'missing': 'expected'}, records=[{'id': 5, 'title': 'Book'}])
        self.write_reference()
        evidence = self.run_reference().reference
        self.assertEqual((evidence.status, evidence.matched, evidence.total), ('failed', 0, 1))
        errors = json.loads((self.output/'comparison.json').read_text())['cases'][0]['differences']
        self.assertEqual({error['kind'] for error in errors}, {'field', 'missing_record'})
        self.assertTrue(any(e['field'] == 'metadata.missing' and e['expected'] == 'expected'
                            and e['actual'] is None for e in errors))
        self.assertTrue(any(e['record_key'] == [5] for e in errors))

    def test_dynamic_totals_and_shared_tool_comparator(self):
        self.write_reference(name='second.json')
        wrong = dict(self.document, status='ok')
        self.write_reference(wrong, 'third.json')
        evidence = self.run_reference().reference
        self.assertEqual((evidence.matched, evidence.total), (2, 3))
        # The existing evaluator imports this compatibility API too.
        import importlib.util
        spec = importlib.util.spec_from_file_location('compare_tool', ROOT/'tools/compare_expected.py')
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        self.assertIs(tool.compare, reference.compare)

    def test_missing_sample_does_not_become_an_engine_failed_result_or_match(self):
        (self.samples/'unknown.dat').unlink()
        evidence = self.run_reference().reference
        self.assertEqual(evidence.status, 'unavailable')
        self.assertIsNone(evidence.matched)
        self.assertIsNone(evidence.agreement.value)
        self.assertFalse((self.output/'actual').exists())

    def test_missing_empty_and_malformed_resources_are_unavailable(self):
        cases = ('empty', 'malformed', 'missing', 'duplicate_key', 'nonfinite', 'overflow')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)/'references'
                folder.mkdir()
                if case == 'malformed':
                    (folder/'one.json').write_text('{')
                if case == 'duplicate_key':
                    (folder/'one.json').write_text('{"file":"a","file":"b"}')
                if case in ('nonfinite', 'overflow'):
                    (folder/'one.json').write_text('{"value": %s}' % ('NaN' if case == 'nonfinite' else '1e999'))
                if case == 'missing':
                    folder.rmdir()
                envelope = reference.run_references(samples_dir=self.samples, expected_dir=folder,
                                                     output_dir=Path(temp)/'proof')
                self.assertEqual(envelope.status, 'unavailable')
                self.assertIsNone(envelope.reference.matched)
                self.assertIsNone(envelope.reference.context.dataset.sha256)

    def test_invalid_reference_shapes_and_escaping_filenames(self):
        bad = [[], {}, dict(self.document, file='../outside'), dict(self.document, file='C:\\outside'),
            dict(self.document, file='/outside'), dict(self.document, format='FAKE'),
            dict(self.document, records=None), dict(self.document, metadata=[]),
            dict(self.document, records=[{}]), dict(self.document, match_on=[]),
            dict(self.document, match_on=['id', 'id']), dict(self.document, match_on=[[]]),
            dict(self.document, records=[{'id': []}]), dict(self.document, expected_damage=[{'any_of': []}]),
            dict(self.document, expected_damage=[{'any_of': ['made_up']}]),
            dict(self.document, expected_damage=[{'any_of': ['truncated'], 'lossy': 1}])]
        for document in bad:
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    reference._validate_reference(document)

    def test_protect_inputs_official_and_existing_recovery_report(self):
        for path in (self.samples, self.samples/'proof', self.expected, self.expected/'proof',
                     self.root, OFFICIAL, OFFICIAL/'new-proof'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                # The measured source kit can be external to the running portable application.
                reference.run_references(samples_dir=self.samples, expected_dir=self.expected,
                                          output_dir=path, source_dir=ROOT)
        self.output.mkdir()
        report = self.output/'report.json'
        report.write_text('existing recovery report')
        with self.assertRaises(ValueError):
            self.run_reference()
        self.assertEqual(report.read_text(), 'existing recovery report')

    def test_precreated_output_is_accepted_only_when_empty_and_never_replaced(self):
        self.output.mkdir()
        self.run_reference()
        before = (self.output/'reference-evidence.json').read_bytes()
        with self.assertRaises(ValueError):
            self.run_reference()
        self.assertEqual((self.output/'reference-evidence.json').read_bytes(), before)

    def test_symlinks_cannot_escape_inputs_or_output_protection(self):
        alias = self.root/'alias'
        try:
            alias.symlink_to(self.samples, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(ValueError):
            reference.run_references(samples_dir=self.samples, expected_dir=self.expected,
                                      output_dir=alias/'proof')
        (self.samples/'unknown.dat').unlink()
        (self.samples/'unknown.dat').symlink_to(self.expected/'answer.json')
        self.assertEqual(self.run_reference().status, 'unavailable')

    def test_engine_failure_cannot_leave_a_passing_comparison(self):
        with mock.patch.object(reference, 'salvage_bytes', side_effect=RuntimeError('synthetic failure')):
            evidence = self.run_reference()
        self.assertEqual(evidence.status, 'unavailable')
        self.assertIsNone(evidence.reference.matched)
        case = json.loads((self.output/'comparison.json').read_text())['cases'][0]
        self.assertIsNone(case['actual'])
        self.assertIn('synthetic failure', case['problem'])
        self.assertFalse((self.output/'actual').exists())

    def test_unusable_actual_matching_key_saves_actual_but_never_passes(self):
        self.document.update(match_on=['printable_strings'], records=[{'printable_strings': 'scalar'}])
        self.write_reference()
        from deadbits.model import Result
        result = Result('unknown.dat')
        result.records = [{'printable_strings': ['array key is unusable']}]
        with mock.patch.object(reference, 'salvage_bytes', return_value=result):
            evidence = self.run_reference()
        self.assertEqual(evidence.status, 'unavailable')
        self.assertIsNone(evidence.reference.matched)
        self.assertTrue((self.output/'actual/0001.json').is_file())

    def test_input_hash_and_decoding_use_the_same_snapshot(self):
        original = (self.samples/'unknown.dat').read_bytes()
        decode = reference.salvage_bytes
        def replace_after_snapshot(payload, name):
            self.assertEqual(payload, original)
            (self.samples/'unknown.dat').write_bytes(b'changed after snapshot')
            return decode(payload, name)
        with mock.patch.object(reference, 'salvage_bytes', side_effect=replace_after_snapshot):
            evidence = self.run_reference()
        self.assertEqual(evidence.status, 'complete')
        manifest = json.loads((self.output/'dataset-manifest.json').read_text())
        item = next(item for item in manifest if item['path'] == 'samples/unknown.dat')
        self.assertEqual(item['sha256'], hashlib.sha256(original).hexdigest())

    def test_resource_limits_are_unavailable(self):
        for setting in ('MAX_REFERENCE_BYTES', 'MAX_REFERENCE_TOTAL_BYTES', 'MAX_SAMPLE_TOTAL_BYTES',
                        'MAX_INPUT_BYTES', 'MAX_REFERENCES'):
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as temp:
                with mock.patch.object(reference, setting, 0):
                    evidence = reference.run_references(samples_dir=self.samples, expected_dir=self.expected,
                                                         output_dir=Path(temp)/'proof')
                self.assertEqual(evidence.status, 'unavailable')

    def test_official_outputs_match_and_optional_partial_is_saved(self):
        envelope = reference.run_references(samples_dir=OFFICIAL/'samples', expected_dir=OFFICIAL/'expected_outputs',
                                             output_dir=self.output)
        self.assertEqual((envelope.reference.matched, envelope.reference.total), (7, 7))
        cases = json.loads((self.output/'comparison.json').read_text())['cases']
        case = next(c for c in cases if c['file'] == 's04.dat')
        actual = json.loads((self.output/case['actual']).read_text())
        self.assertTrue(any(record['id'] == 1040 for record in actual['records']))
        self.assertEqual(case['differences'], [])

    def test_live_cli_prints_saved_artifact_paths_against_evidence_directory(self):
        from deadbits.cli import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--verify', '--samples-dir', str(self.samples), '--expected-dir',
                         str(self.expected), '--evidence-dir', str(self.output)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn(str(self.output.resolve()/'actual/0001.json'), out.getvalue())
        self.assertIn(str(self.output.resolve()/'comparison.json'), out.getvalue())

    def test_cli_dispatch_saves_envelope_and_installed_mode_explains_missing_kit(self):
        request = ValidationRequest(samples_dir=self.samples, expected_dir=self.expected, evidence_dir=self.output)
        evidence = run_validation('verify', request)
        self.assertEqual(evidence.status, 'complete')
        saved = ValidationEvidence.from_dict(json.loads((self.output/'validation.json').read_text()))
        self.assertEqual(saved, evidence)
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)/'salvage.pyz'
            with zipfile.ZipFile(app, 'w') as archive:
                archive.writestr('__main__.py', 'from deadbits.cli import main\nraise SystemExit(main())\n')
                for path in (ROOT/'deadbits').rglob('*.py'):
                    archive.write(path, path.relative_to(ROOT).as_posix())
            missing = subprocess.run([sys.executable, str(app), '--verify', '--evidence-dir', str(Path(temp)/'missing')],
                                     cwd=temp, capture_output=True, text=True, timeout=20)
            self.assertEqual(missing.returncode, 3, missing.stderr)
            self.assertIn('--kit-dir', missing.stdout)
            live = subprocess.run([sys.executable, str(app), '--verify', '--samples-dir', str(self.samples),
                '--expected-dir', str(self.expected), '--evidence-dir', str(Path(temp)/'installed proof é')],
                cwd=temp, capture_output=True, text=True, timeout=20)
            self.assertEqual(live.returncode, 0, live.stderr)
            self.assertIn('1/1 (100.0%)', live.stdout)


class Matching(unittest.TestCase):
    def setUp(self):
        self.actual = dict(format='LIBRA-98', status='partial', metadata={'requested': 1, 'extra': 2},
            records=[{'id': 1, 'title': 'Book', 'extra': True}, {'id': 2, 'unchecked': 'allowed'}],
            damage=[{'kind': 'truncated', 'lossy': False}])
        self.expected = dict(format='LIBRA-98', status='partial', metadata={'requested': 1},
            records=[{'id': 1, 'title': 'Book'}], optional_partial_records=[{'id': 2}],
            match_on=['id'], expected_damage=[{'any_of': ['truncated', 'bad_length'], 'lossy': True}])

    def test_optional_identity_metadata_subset_and_kind_only_damage_rules(self):
        self.assertEqual(reference.compare(self.actual, self.expected), [])
        # Legacy behavior: optional record fields, extra damage and lossy are not compared.
        self.actual['damage'].append({'kind': 'count_mismatch'})
        self.assertEqual(reference.compare(self.actual, self.expected), [])

    def test_missing_extra_and_field_differences_have_record_keys(self):
        self.actual['records'] = [{'id': 1, 'title': 'Wrong'}, {'id': 99}]
        self.expected['records'].append({'id': 3, 'title': 'Missing'})
        errors = reference.differences(self.actual, self.expected)
        self.assertEqual([e['kind'] for e in errors], ['field', 'missing_record', 'extra_record'])
        self.assertEqual([e['record_key'] for e in errors], [[1], [3], [99]])
        self.assertEqual(errors[0]['expected'], 'Book')
        self.assertEqual(errors[0]['actual'], 'Wrong')

    def test_damage_alternatives_and_empty_damage_expectation(self):
        self.actual['damage'] = []
        self.assertIn('expected damage any_of', reference.compare(self.actual, self.expected)[0])
        self.expected['expected_damage'] = []
        self.actual['damage'] = [{'kind': 'truncated'}]
        self.assertEqual(reference.compare(self.actual, self.expected), ["unexpected damage: ['truncated']"])

    def test_composite_keys_and_last_duplicate_match_legacy_behavior(self):
        self.expected['match_on'] = ['id', 'title']
        self.expected['optional_partial_records'] = []
        self.actual['records'] = [{'id': 1, 'title': 'Book', 'v': 0}, {'id': 1, 'title': 'Book', 'v': 9}]
        self.expected['records'] = [{'id': 1, 'title': 'Book', 'v': 9}]
        self.assertEqual(reference.compare(self.actual, self.expected), [])
