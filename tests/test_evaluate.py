"""Independent assertions for evaluation honesty and deterministic mutations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from evaluate import (aggregate, compare_records, decode, evaluate, load_corpus,
                      make_baseline)  # noqa: E402
from make_variants import MUTATIONS, OFFICIAL, create_corpus, variants  # noqa: E402


def document(records=(), fmt='PAK', status='ok'):
    return {'format': fmt, 'status': status, 'records': list(records)}


def archive(name='a', digest='abc'):
    return {'name': name, 'offset': 12, 'size': 3, 'sha256': digest}


class VariantTests(unittest.TestCase):
    def test_six_mutations_are_exact_and_repeatable(self):
        data = bytes(range(100))
        cases = list(variants(data))
        self.assertEqual(tuple(v[0] for v in cases), MUTATIONS)
        self.assertEqual(cases, list(variants(data)))
        self.assertEqual([len(v[1]) for v in cases[:4]], [10, 50, 90, 99])
        self.assertEqual(sum(a != b for a, b in zip(data, cases[4][1])), 1)
        self.assertEqual(cases[4][1][50], 50 ^ 255)
        self.assertEqual(cases[5][1][34:66], bytes(32))
        self.assertEqual(cases[5][1][:34], data[:34])
        self.assertEqual(cases[5][1][66:], data[66:])
        self.assertEqual(data, bytes(range(100)))

    def test_empty_and_tiny_inputs_are_explicit_not_skipped(self):
        self.assertEqual(len(list(variants(b''))), 6)
        self.assertTrue(all(not data for _, data, _ in variants(b'')))
        tiny = list(variants(b'x'))
        self.assertEqual([len(v[1]) for v in tiny], [0, 0, 0, 0, 1, 1])

    def test_saved_corpus_round_trips_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / 'source', root / 'variants'
            source.mkdir()
            (source / 'known.dat').write_bytes(b'abcd')
            (source / 'empty.dat').write_bytes(b'')
            (source / 'nested').mkdir()
            (source / 'nested' / 'ignored.dat').write_bytes(b'ignored')
            manifest = create_corpus(source, output)
            self.assertEqual(len(manifest['sources']), 2)
            self.assertEqual(len(manifest['variants']), 12)
            self.assertEqual((source / 'known.dat').read_bytes(), b'abcd')
            saved = (output / 'manifest.json').read_bytes()
            create_corpus(source, output)
            self.assertEqual((output / 'manifest.json').read_bytes(), saved)
            sources = {'known.dat': b'abcd', 'empty.dat': b''}
            self.assertEqual(len(load_corpus(output, sources)), 12)
            first = manifest['variants'][0]
            (output / first['file']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'deterministic mutation'):
                load_corpus(output, sources)

    def test_corpus_refuses_source_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'outside'):
                create_corpus(temp, Path(temp) / 'nested')
            self.assertFalse((Path(temp) / 'nested').exists())
            with self.assertRaisesRegex(ValueError, 'outside'):
                create_corpus(temp, OFFICIAL / 'generated-variants')

    def test_corpus_refuses_existing_output_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / 'source', root / 'variants'
            source.mkdir()
            output.mkdir()
            (source / 'a').write_bytes(b'abcd')
            protected = root / 'protected'
            protected.write_bytes(b'unchanged')
            (output / 'a.truncate_10.bin').symlink_to(protected)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                create_corpus(source, output)
            self.assertEqual(protected.read_bytes(), b'unchanged')

    def test_corpus_requires_all_mutations_and_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / 'source', root / 'variants'
            source.mkdir()
            (source / 'a').write_bytes(b'abcd')
            manifest = create_corpus(source, output)
            with self.assertRaisesRegex(ValueError, 'source differs'):
                load_corpus(output, {'a': b'changed'})
            manifest['variants'].pop()
            (output / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'all six'):
                load_corpus(output, {'a': b'abcd'})


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.truth = archive()
        self.baseline = make_baseline(document([self.truth]))

    def test_identity_recovery_does_not_hide_wrong_verified_fields(self):
        counts = compare_records(document([archive(digest='wrong')]), self.baseline)
        self.assertEqual(counts['recovered_records'], 1)
        self.assertEqual(counts['correct_records'], 0)
        self.assertEqual(counts['wrong_records'], 1)
        self.assertEqual(counts['false_verified_records'], 1)
        flagged = dict(archive(digest='wrong'), verified=False, issues=['truncated'])
        counts = compare_records(document([flagged]), self.baseline)
        self.assertEqual(counts['wrong_records'], 1)
        self.assertEqual(counts['false_verified_records'], 0)

    def test_omitted_field_is_incomplete_unequal_null_is_wrong(self):
        missing = dict(self.truth)
        del missing['sha256']
        counts = compare_records(document([missing]), self.baseline)
        self.assertEqual(counts['recovered_records'], 1)
        self.assertEqual(counts['incomplete_records'], 1)
        self.assertEqual(counts['false_verified_records'], 0)
        self.assertEqual(counts['correct_records'], 0)
        missing['sha256'] = None
        counts = compare_records(document([missing]), self.baseline)
        self.assertEqual(counts['wrong_records'], 1)
        self.assertEqual(counts['false_verified_records'], 1)

    def test_missing_identity_unexpected_identity_and_duplicates_are_counted(self):
        no_key = dict(self.truth)
        del no_key['name']
        counts = compare_records(document([no_key, archive('invented')]), self.baseline)
        self.assertEqual(counts['missing_records'], 1)
        self.assertEqual(counts['unexpected_records'], 2)
        self.assertEqual(counts['false_verified_records'], 2)
        counts = compare_records(document([self.truth, self.truth]), self.baseline)
        self.assertEqual(counts['correct_records'], 1)
        self.assertEqual(counts['unexpected_records'], 1)

    def test_wrong_format_cannot_claim_recovery(self):
        counts = compare_records(document([self.truth], fmt='WAD'), self.baseline)
        self.assertEqual(counts['recovered_records'], 0)
        self.assertEqual(counts['missing_records'], 1)

    def test_original_partial_and_unverified_records_are_not_truth(self):
        uncertain = dict(archive('b'), verified=False)
        baseline = make_baseline(document([self.truth, uncertain], status='partial'))
        self.assertEqual(baseline['records'], [self.truth])
        self.assertEqual(baseline['excluded_unverified'], 1)
        counts = compare_records(document([self.truth, archive('b'), archive('new')]), baseline)
        self.assertEqual(counts['expected_records'], 1)
        self.assertEqual(counts['correct_records'], 1)
        self.assertEqual(counts['unassessed_records'], 2)
        self.assertEqual(counts['false_verified_records'], 0)

    def test_optional_reference_record_never_inflates_recovery(self):
        expected = {'format': 'PAK', 'match_on': ['name'], 'records': [self.truth],
                    'optional_partial_records': [{'name': 'optional'}]}
        baseline = make_baseline(document([], status='partial'), expected)
        counts = compare_records(document([archive('optional')]), baseline)
        self.assertEqual(baseline['kind'], 'organizer_reference')
        self.assertEqual(counts['expected_records'], 1)
        self.assertEqual(counts['recovered_records'], 0)
        self.assertEqual(counts['optional_records'], 1)
        self.assertEqual(counts['unassessed_records'], 1)
        self.assertEqual(counts['false_verified_records'], 0)

    def test_no_record_denominator_is_not_success(self):
        baseline = make_baseline(document([], 'UNKNOWN', 'unrecognized'))
        counts = compare_records(document([], 'UNKNOWN', 'unrecognized'), baseline)
        report = aggregate([counts])
        self.assertIsNone(report['record_recovery_rate'])
        self.assertIsNone(report['complete_record_rate'])
        self.assertIsNone(report['format_coverage_rate'])

    def test_decoder_exceptions_escaping_and_caught_by_engine_are_crashes(self):
        def broken(data, name):
            raise ValueError('bad decoder')
        doc, crashed = decode(b'x', 'a', broken)
        self.assertTrue(crashed)
        self.assertEqual(doc['status'], 'failed')

        class Caught:
            notes = ['decoder exception: ValueError()']

            def to_dict(self):
                return document([], status='failed')

        self.assertTrue(decode(b'x', 'a', lambda d, n: Caught())[1])

    def test_full_report_separates_reference_regression_and_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            samples, refs, corpus = root / 'samples', root / 'expected', root / 'variants'
            samples.mkdir()
            refs.mkdir()
            for name, data in [('ref', b'original'), ('reg', b'original'), ('empty', b'')]:
                (samples / name).write_bytes(data)
            (refs / 'ref.json').write_text(json.dumps({
                'file': 'ref', 'format': 'PAK', 'match_on': ['name'], 'records': [self.truth]}))

            def fake(data, name):
                if name == 'empty':
                    return document([], 'UNKNOWN', 'unrecognized')
                if data == b'original':
                    return document([self.truth])
                return document([archive(digest='wrong')])

            create_corpus(samples, corpus)
            result = evaluate(samples, refs, fake)
            persisted = evaluate(samples, refs, fake, corpus)
            self.assertEqual(result, persisted)
            self.assertEqual(result['samples'], 3)
            self.assertEqual(result['variants'], 18)
            self.assertEqual(result['changed_variants'], 12)
            self.assertEqual(result['unchanged_variants'], 6)
            self.assertEqual(result['summary']['false_verified_records'], 12)
            self.assertEqual(result['by_baseline']['organizer_reference']['false_verified_records'], 6)
            self.assertEqual(result['by_baseline']['regression_baseline']['false_verified_records'], 6)
            self.assertIsNone(result['by_baseline']['no_record_baseline']['record_recovery_rate'])
            self.assertEqual(result['baselines']['reg']['kind'], 'regression_baseline')
            self.assertEqual(result['summary']['crashes'], 0)
            self.assertEqual(len(result['cases']), 18)


if __name__ == '__main__':
    unittest.main()
