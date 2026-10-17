"""Judge-facing visuals retain actual counts, uncertainty and terminal safety."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deadbits import presentation as ui
from deadbits.cli import run
from deadbits.validation.model import (Artifact, BenchmarkEvidence, Context, Ratio,
    RecordAccuracy, ReferenceEvidence, Resource, TestEvidence, ValidationEvidence)


class TerminalUI(unittest.TestCase):
    def test_recovery_charts_show_counts_not_invented_accuracy(self):
        report = dict(files=[dict(file='a', format='WKS', status='ok', records=2, damage=0),
                            dict(file='b', format='WKS', status='partial', records=1, damage=1)],
                      totals=dict(ok=1, partial=1, failed=0))
        text = ui.recovery(report, verbose=True)
        self.assertIn('DEADBITS', text)
        self.assertIn('Recovered records: 3; damage entries: 1', text)
        self.assertIn('No loss detected', text)
        self.assertIn('Some data lost or unverified', text)
        self.assertIn('Accuracy unavailable', text)
        self.assertNotIn('%', text)
        self.assertIn('FILE RESULTS', text)
        self.assertNotIn('[............]  1', text)

    def test_unknown_and_zero_denominators_have_no_full_bar(self):
        self.assertIn('?', ui.bar(None, 10))
        self.assertIn('?', ui.bar(0, 0))
        self.assertEqual(ui.bar(0, 10, 4), '[....]')
        self.assertEqual(ui.bar(1, 1000, 4), '[#...]')
        self.assertEqual(ui.bar(10, 10, 4), '[####]')
        text = ui.meter('Accuracy', Ratio(0, 0))
        self.assertIn('unavailable', text)
        self.assertNotIn('100.0%', text)

    def test_accuracy_panels_use_actual_denominators_and_historical_provenance(self):
        evidence = ValidationEvidence(reference=ReferenceEvidence(matched=0, total=1,
            context=Context(provenance='historical'),
            record_accuracy=RecordAccuracy(expected=4, recovered=3, correct=2,
                                          wrong=1, missing=1, unexpected=1)))
        text = ui.validation(evidence)
        self.assertIn('historical', text)
        self.assertIn('3/4 (75.0%)', text)
        self.assertIn('2/4 (50.0%)', text)
        self.assertIn('Wrong matching records', text)
        self.assertIn('files without answers are not scored', text)

    def test_narrow_panels_wrap_without_omitting_values(self):
        with patch.dict(os.environ, {'COLUMNS': '40'}):
            text = ui.panel('Results', ui.table(('File', 'Records'), [('a'*80, 123)]))
        self.assertTrue(all(len(line) <= 40 for line in text.splitlines()))
        self.assertIn('Records: 123', text)
        self.assertEqual(text.count('a'), 80)

    def test_record_cards_keep_uncertainty_and_escape_controls(self):
        text = ui.record_card(dict(id=7, title='demo\x1b[31m\nforged', verified=False,
                                   issues=['checksum_mismatch']))
        self.assertIn('Unverified record:', text)
        self.assertIn('checksum_mismatch', text)
        self.assertNotIn('\x1b', text)
        self.assertIn('\\u001b', text)
        self.assertIn('Check issues', text)

    def test_byte_diagrams_use_exact_mutation_counts_and_offsets(self):
        cut = ui.byte_change('truncation', dict(keep_bytes=75), 100, 75)
        self.assertIn('100 original bytes -> 75 kept; 25 removed', cut)
        self.assertIn('scaled view', cut)
        flip = ui.byte_change('checksum', dict(offset=23, xor=1), 100, 100)
        self.assertIn('Byte 23 XOR 1; length stays 100 bytes.', flip)
        self.assertIn('X marks', flip)

    def test_redirected_output_is_plain_and_no_color_is_respected(self):
        class Terminal(io.StringIO):
            def isatty(self): return True
        for stream, environment, colored in (
            (io.StringIO(), {'TERM': 'xterm'}, False),
            (Terminal(), {'TERM': 'xterm', 'WT_SESSION': 'test'}, True),
            (Terminal(), {'TERM': 'xterm', 'NO_COLOR': ''}, False),
            (Terminal(), {'TERM': 'dumb'}, False)):
            with patch.dict(os.environ, environment, clear=True):
                ui.emit(ui.panel('Result', 'safe'), stream)
            self.assertEqual('\x1b[' in stream.getvalue(), colored)
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='ascii')
        ui.emit(ui.record_card(dict(title='livre é')), stream)
        stream.flush()
        self.assertIn(b'\\u00e9', raw.getvalue())

    def test_compact_validation_keeps_failures_and_benchmark_baselines_visible(self):
        evidence = ValidationEvidence(tests=TestEvidence(passed=1, failed=1, errors=0,
            skipped=0, expected_failures=0, unexpected_successes=0,
            artifacts=(Artifact('test_log', 'tests.log'),)), benchmarks=(
                BenchmarkEvidence(baseline='regression_baseline', format='WKS', cases=2, crashes=1),))
        text = ui.validation(evidence, evidence_file=Path('/tmp/proof/validation.json'), compact=True)
        self.assertIn('Tests: failed', text)
        self.assertIn('regression_baseline', text)
        self.assertIn('not independent accuracy', text)
        self.assertIn('/ failed / unknown', text)
        self.assertIn('Full evidence: /tmp/proof/validation.json', text)
        self.assertNotIn('test_log:', text)

    def test_ui_does_not_change_recovery_json_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = root/'inputs'
            inputs.mkdir()
            (inputs/'unknown.bin').write_bytes(b'\0\xff\0\xff')
            report = run(inputs, root/'one')
            before = {p.name: p.read_bytes() for p in (root/'one').iterdir()}
            ui.recovery(report, verbose=True)
            run(inputs, root/'two')
            self.assertEqual(before, {p.name: p.read_bytes() for p in (root/'two').iterdir()})
            self.assertEqual(before, {p.name: p.read_bytes() for p in (root/'one').iterdir()})

    def test_resource_controls_are_escaped_even_in_visual_validation(self):
        evidence = ValidationEvidence(reference=ReferenceEvidence(resources=(
            Resource('bad\x1b[31m', False, 'line\nforged'),)))
        text = ui.validation(evidence)
        self.assertNotIn('\x1b', text)
        self.assertIn('line\\x0aforged', text)
