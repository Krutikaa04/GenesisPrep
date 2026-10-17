"""Dynamic accuracy against independent answers, including wrong/missing output."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from deadbits.cli import main
from deadbits.validation.model import RecordAccuracy, ReferenceEvidence, ValidationEvidence
from deadbits.validation.reference import record_accuracy


def worksheet(cells):
    def frame(op, payload=b''):
        return struct.pack('<HH', op, len(payload)) + payload
    return (frame(0, struct.pack('<H', 0x0404)) +
            b''.join(frame(13, struct.pack('<BHHh', 255, col, 0, value))
                     for col, value in cells) + frame(1))


class DynamicReferenceAccuracy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.samples, self.answers = self.root/'inputs', self.root/'answers'
        self.samples.mkdir()
        self.answers.mkdir()
        (self.samples/'new.wks').write_bytes(worksheet([(0, 7), (1, 8), (2, 9), (3, 10)]))
        self.answer = dict(file='new.wks', format='WKS', status='ok', match_on=['cell'],
                           records=[dict(cell='A1', value=7), dict(cell='B1', value=99),
                                    dict(cell='E1', value=11)],
                           optional_partial_records=[dict(cell='D1')])
        self.save_answer()

    def save_answer(self):
        (self.answers/'answer.json').write_text(json.dumps(self.answer), encoding='utf-8')

    def invoke(self, name='proof', extra=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(extra or ['--verify', '--samples-dir', str(self.samples),
                        '--expected-dir', str(self.answers), '--evidence-dir', str(self.root/name)])
        return code, out.getvalue(), err.getvalue()

    def evidence(self, name='proof'):
        return ValidationEvidence.from_dict(json.loads((self.root/name/'validation.json').read_text()))

    def test_live_cli_measures_independent_wrong_missing_unexpected_and_optional_records(self):
        before = (self.samples/'new.wks').read_bytes()
        code, text, err = self.invoke()
        self.assertEqual(code, 1, err)
        score = self.evidence().reference.record_accuracy
        self.assertEqual(score, RecordAccuracy(expected=3, recovered=2, correct=1,
                                              wrong=1, missing=1, unexpected=1, optional=1))
        self.assertIn('2/3 (66.7%)', text)
        self.assertIn('1/3 (33.3%)', text)
        self.assertIn('Record accuracy (supplied fields)', text)
        self.assertIn('Unexpected records', text)
        self.assertIn('files without answers are not scored', text)
        self.assertEqual((self.samples/'new.wks').read_bytes(), before)
        case = json.loads((self.root/'proof/comparison.json').read_text())['cases'][0]
        summary = json.loads((self.root/'proof/summary.json').read_text())
        self.assertEqual(case['record_accuracy'], score.to_dict())
        self.assertEqual(summary['record_accuracy'], score.to_dict())

    def test_new_input_bytes_change_live_results_instead_of_replaying_a_percentage(self):
        self.answer.update(records=[dict(cell='A1', value=7)], optional_partial_records=[])
        self.save_answer()
        (self.samples/'new.wks').write_bytes(worksheet([(0, 7)]))
        self.assertEqual(self.invoke('first')[0], 0)
        (self.samples/'new.wks').write_bytes(worksheet([(0, 8)]))
        code, text, _ = self.invoke('second')
        self.assertEqual(code, 1)
        self.assertEqual(self.evidence('first').reference.record_accuracy.correct, 1)
        self.assertEqual(self.evidence('second').reference.record_accuracy.correct, 0)
        self.assertIn('0/1 (0.0%)', text)
        self.assertNotEqual(self.evidence('first').reference.context.dataset.sha256,
                            self.evidence('second').reference.context.dataset.sha256)

    def test_multiple_files_use_summed_counts_not_average_percentages_and_ignore_unreferenced_files(self):
        (self.samples/'second.wks').write_bytes(worksheet([(0, 5)]))
        (self.answers/'second.json').write_text(json.dumps(dict(file='second.wks', format='WKS',
            status='ok', match_on=['cell'], records=[dict(cell='A1', value=5)])))
        (self.samples/'without-answer.bin').write_bytes(b'unscored')
        self.invoke()
        score = self.evidence().reference.record_accuracy
        self.assertEqual((score.expected, score.recovered, score.correct), (4, 3, 2))
        self.assertEqual(score.measurements['accuracy'].value, 0.5)
        self.assertEqual(score.measurements['precision'].value, 0.5)

    def test_empty_expected_records_never_produce_a_100_percent_record_accuracy(self):
        self.answer.update(records=[], optional_partial_records=[])
        self.save_answer()
        code, text, _ = self.invoke()
        self.assertEqual(code, 1)
        score = self.evidence().reference.record_accuracy
        self.assertIsNone(score.measurements['accuracy'].value)
        self.assertEqual(score.unexpected, 4)
        self.assertIn('references contain no required records', text)

    def test_missing_answers_or_missing_sample_have_no_partial_aggregate_accuracy(self):
        (self.answers/'answer.json').unlink()
        self.assertEqual(self.invoke('no-answers')[0], 3)
        self.assertIsNone(self.evidence('no-answers').reference.record_accuracy)
        self.save_answer()
        (self.samples/'new.wks').unlink()
        code, text, _ = self.invoke('no-input')
        self.assertEqual(code, 3)
        self.assertIn('Record accuracy unavailable', text)
        self.assertIsNone(self.evidence('no-input').reference.record_accuracy)

    def test_historical_rates_survive_roundtrip_and_are_labelled_historical(self):
        self.invoke()
        path = self.root/'proof/validation.json'
        before = path.read_bytes()
        code, text, _ = self.invoke(extra=['--verify', '--evidence-file', str(path)])
        self.assertEqual(code, 1)
        self.assertIn('historical', text)
        self.assertIn('1/3 (33.3%)', text)
        self.assertEqual(path.read_bytes(), before)
        old = self.root/'old.json'
        old.write_text(json.dumps(dict(schema_version=1, reference=dict(matched=7, total=7))))
        code, text, _ = self.invoke(extra=['--verify', '--evidence-file', str(old)])
        self.assertEqual(code, 0)
        self.assertIn('record measurements were not saved', text)

    def test_repeated_answers_do_not_double_count_a_file(self):
        (self.answers/'duplicate.json').write_text(json.dumps(self.answer))
        self.invoke()
        section = self.evidence().reference
        self.assertEqual(section.total, 2)
        self.assertIsNone(section.record_accuracy)
        self.assertIn('multiple reference answers', section.record_accuracy_detail)


class AccuracySemantics(unittest.TestCase):
    def test_format_mismatch_and_absent_null_field_are_not_correct_records(self):
        expected = dict(format='WKS', records=[dict(id=1, value=None)])
        for actual in (dict(format='WKS', records=[dict(id=1)]),
                       dict(format='LIBRA-98', records=[dict(id=1, value=None)])):
            score = record_accuracy(actual, expected)
            self.assertEqual((score.recovered, score.correct, score.wrong), (1, 0, 1))

    def test_duplicate_incomplete_or_overlapping_identities_do_not_hide_bad_records(self):
        expected = dict(format='WKS', records=[dict(id=1)])
        for records in ([dict(id=1), dict(id=1)], [dict(value=1)]):
            with self.assertRaises(ValueError):
                record_accuracy(dict(format='WKS', records=records), expected)
        with self.assertRaises(ValueError):
            record_accuracy(dict(format='WKS', records=[]),
                            dict(expected, optional_partial_records=[dict(id=1)]))

    def test_composite_keys_correctly_match_reordered_records_and_ignore_extra_fields(self):
        expected = dict(format='WKS', match_on=['row', 'col'],
                        records=[dict(row=1, col=2, value=7), dict(row=2, col=1, value=8)])
        actual = dict(format='WKS', records=[dict(row=2, col=1, value=8),
                                             dict(row=1, col=2, value=7, extra=True)])
        self.assertEqual(record_accuracy(actual, expected).correct, 2)

    def test_impossible_or_tampered_evidence_counts_and_rates_are_rejected(self):
        for changes in (dict(expected=True), dict(expected=-1), dict(correct=1), dict(expected=None)):
            with self.assertRaises(ValueError):
                RecordAccuracy(**changes)
        doc = ValidationEvidence(reference=ReferenceEvidence(matched=1, total=1,
            record_accuracy=RecordAccuracy(expected=1, recovered=1, correct=1))).to_dict()
        self.assertEqual(ValidationEvidence.from_dict(doc).to_dict(), doc)
        doc['reference']['record_accuracy']['measurements']['accuracy']['value'] = 0.5
        with self.assertRaises(ValueError):
            ValidationEvidence.from_dict(doc)

    def test_ordinary_recovery_still_has_no_accuracy_without_answers(self):
        from deadbits.presentation import recovery
        text = recovery(dict(files=[], totals={}))
        self.assertIn('Accuracy unavailable', text)
        self.assertNotIn('%', text)
