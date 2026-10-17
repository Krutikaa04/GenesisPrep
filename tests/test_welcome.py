"""Beginner workflows use real output and preserve source/evidence folders."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from deadbits import cli, welcome
from test_reference_accuracy import worksheet


class WelcomeMenu(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.inputs = self.root/'input files ü & $literal'
        self.inputs.mkdir()
        self.original = worksheet([(0, 7)])
        (self.inputs/'sheet.bin').write_bytes(self.original)
        self.output = self.root/'new results'

    def menu(self, lines, **kwargs):
        out = io.StringIO()
        code = welcome.run_menu(io.StringIO(lines), out, **kwargs)
        return code, out.getvalue()

    def test_recovery_by_quoted_paths_and_open_results_uses_actual_engine(self):
        opener = Mock()
        code, text = self.menu('1\n"%s"\n"%s"\ny\ny\n5\n' % (self.inputs, self.output), opener=opener)
        self.assertEqual(code, 0)
        result = json.loads((self.output/'sheet.bin.json').read_text())
        self.assertEqual((result['format'], result['status'], result['records'][0]['value']), ('WKS', 'ok', 7))
        self.assertIn('Accuracy unavailable', text)
        self.assertIn('Results saved at:', text)
        self.assertEqual((self.inputs/'sheet.bin').read_bytes(), self.original)
        opener.assert_called_once_with(self.output)

    def test_no_confirmation_means_no_output_or_external_actions(self):
        opener = Mock()
        self.menu('1\n%s\n%s\nn\n5\n' % (self.inputs, self.output), opener=opener)
        self.assertFalse(self.output.exists())
        opener.assert_not_called()

    def test_browse_results_selects_a_parent_and_creates_a_new_child(self):
        chooser = Mock(side_effect=[str(self.inputs), str(self.root)])
        with patch.object(welcome, 'suggested_output', return_value=self.root/'suggested-child'):
            _, text = self.menu('1\nb\nb\ny\nn\n5\n', chooser=chooser)
        self.assertEqual(chooser.call_count, 2)
        self.assertTrue((self.root/'suggested-child/report.json').is_file())
        self.assertIn('a new results folder', text)

    def test_optional_picker_failure_or_cancel_returns_to_typed_paths(self):
        for picker in (Mock(side_effect=RuntimeError('no Tk/display')), Mock(return_value='')):
            code, text = self.menu('1\nb\nq\n5\n', chooser=picker)
            self.assertEqual(code, 0)
            self.assertIn('menu', text)
            self.assertFalse(self.output.exists())

    def test_invalid_input_and_existing_output_do_not_overwrite_previous_results(self):
        self.output.mkdir()
        (self.output/'report.json').write_text('keep previous report')
        new = self.root/'another output'
        _, text = self.menu('1\n%s\n%s\n%s\n%s\ny\nn\n5\n' %
                            (self.root/'absent', self.inputs, self.output, new))
        self.assertIn('folder was not found', text)
        self.assertIn('Existing folders are preserved', text)
        self.assertEqual((self.output/'report.json').read_text(), 'keep previous report')
        self.assertTrue((new/'report.json').is_file())

    def test_output_inside_input_is_rejected(self):
        _, text = self.menu('1\n%s\n%s\n5\n' % (self.inputs, self.inputs/'new'))
        self.assertIn('outside the input folder', text)
        self.assertFalse((self.inputs/'new').exists())

    def test_eof_at_menu_or_during_recovery_exits_without_hanging(self):
        for script in ('', '1\n', '1\n%s\n' % self.inputs, 'nonsense\n'):
            code, text = self.menu(script)
            self.assertEqual(code, 0)
            self.assertIn('Input ended', text)
            self.assertFalse(self.output.exists())

    def test_failed_folder_open_does_not_lose_saved_recovery(self):
        _, text = self.menu('1\n%s\n%s\ny\ny\n5\n' % (self.inputs, self.output),
                            opener=Mock(side_effect=OSError('no file manager')))
        self.assertIn('Could not open a file manager', text)
        self.assertTrue((self.output/'report.json').exists())

    def test_reference_workflow_calculates_dynamic_accuracy(self):
        answers = self.root/'answers'
        answers.mkdir()
        (answers/'sheet.json').write_text(json.dumps(dict(file='sheet.bin', format='WKS', status='ok',
            match_on=['cell'], records=[dict(cell='A1', value=7)])))
        code, text = self.menu('3\n%s\n%s\n%s\nn\n5\n' % (self.inputs, answers, self.output))
        self.assertEqual(code, 0)
        self.assertIn('1/1 (100.0%)', text)
        self.assertIn('Comparison exit: 0', text)
        self.assertTrue((self.output/'validation.json').is_file())

    def test_demo_requires_explicit_trust_before_executing_source_kit_code(self):
        source = self.root/'source'
        for name in ('tests', 'tools', 'samples/official'):
            (source/name).mkdir(parents=True, exist_ok=True)
        for trusted in ('n', 'y'):
            with patch.object(cli, 'main', return_value=3) as run:
                self.menu('2\n%s\n%s\n%s\n5\n' % (source, self.output, trusted))
            args = run.call_args.args[0]
            self.assertEqual('--source-dir' in args, trusted == 'y')
            self.assertIn(str(source/'samples/official'), args)

    def test_doctor_explains_optional_resources_and_invalid_choices_are_recoverable(self):
        _, text = self.menu('9\n4\n5\n')
        self.assertIn('Enter a number from 1 to 5', text)
        self.assertIn('Missing optional validation resources', text)
        self.assertIn('SYSTEM CHECK', text)

    def test_no_argument_tty_opens_menu_but_redirected_legacy_usage_stays_zero(self):
        class Terminal(io.StringIO):
            def isatty(self): return True
        incoming, outgoing = Terminal('5\n'), Terminal()
        with patch.object(sys, 'stdin', incoming), patch.object(sys, 'stdout', outgoing):
            self.assertEqual(cli.main([]), 0)
        self.assertIn('WHAT WOULD YOU LIKE TO DO', outgoing.getvalue())
        with patch.object(sys, 'stdin', io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([]), 0)

    def test_explicit_interactive_mode_works_in_portable_scripted_sessions(self):
        result = subprocess.run([sys.executable, '-m', 'deadbits.cli', '--interactive'],
                                input='5\n', text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Goodbye', result.stdout)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--interactive', '--doctor']), 2)


if __name__ == '__main__':
    unittest.main()
