"""Known-answer checks for evidence semantics, independent of decoder output."""
from dataclasses import FrozenInstanceError
import json
import unittest

from deadbits.validation.model import (
    Artifact, BenchmarkEvidence, Context, Dataset, Environment, Ratio,
    ReferenceEvidence, Resource, TestEvidence, ValidationEvidence,
)


def suite(**changes):
    outcomes = dict(passed=2, failed=0, errors=0, skipped=0,
                    expected_failures=0, unexpected_successes=0)
    outcomes.update(changes)
    return TestEvidence(**outcomes)


def benchmark(**changes):
    counts = dict(baseline="organizer_reference", cases=4, crashes=0,
                  expected_records=10, recovered_records=8, complete_records=5,
                  assessed_records=9, assessed_verified_records=6,
                  wrong_records=3, false_verified_records=2)
    counts.update(changes)
    return BenchmarkEvidence(**counts)


class RatioTests(unittest.TestCase):
    def test_known_zero_differs_from_unknown_and_empty(self):
        self.assertEqual(Ratio(0, 4).value, 0.0)
        for value in (Ratio(), Ratio(0, 0), Ratio(None, 4), Ratio(0, None)):
            with self.subTest(value=value):
                self.assertIsNone(value.value)
        self.assertEqual(Ratio(3, 4).to_dict(),
                         {"numerator": 3, "denominator": 4, "value": 0.75})

    def test_invalid_counts_cannot_be_coerced_into_passes(self):
        for value in (-1, True, 1.0, "1", float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Ratio(value, 3)
                with self.assertRaises(ValueError):
                    Ratio(0, value)
        with self.assertRaises(ValueError):
            Ratio(2, 1)


class ReferenceAndTestEvidenceTests(unittest.TestCase):
    def test_reference_matching_is_not_record_recovery(self):
        reference = ReferenceEvidence(matched=7, total=7)
        self.assertEqual(reference.status, "passed")
        self.assertEqual(reference.agreement.value, 1.0)
        self.assertNotIn("recovery", reference.to_dict())
        self.assertEqual(ReferenceEvidence(matched=6, total=7).status, "failed")
        with self.assertRaises(ValueError):
            ReferenceEvidence(matched=8, total=7)

    def test_missing_empty_or_unknown_reference_run_never_passes(self):
        for value in (ReferenceEvidence(), ReferenceEvidence(matched=0, total=0),
                      ReferenceEvidence(total=7), ReferenceEvidence(matched=7, total=7,
                          resources=(Resource("expected directory", False, "not found"),))):
            with self.subTest(value=value):
                self.assertEqual(value.status, "unavailable")

    def test_outcomes_are_dynamic_and_skips_do_not_become_passes(self):
        value = suite(passed=12, skipped=3, expected_failures=1)
        self.assertEqual(value.total, 16)
        self.assertEqual(value.success.value, 12 / 16)
        self.assertEqual(value.status, "passed")
        self.assertEqual(value.to_dict()["skipped"], 3)

    def test_empty_skipped_only_or_incomplete_test_counts_do_not_pass(self):
        for value in (TestEvidence(), suite(passed=0), suite(passed=0, skipped=7),
                      suite(errors=None), suite(resources=(Resource("test discovery", None),))):
            with self.subTest(value=value):
                self.assertEqual(value.status, "unavailable")
        self.assertIsNone(suite(errors=None).total)
        self.assertIsNone(suite(errors=None).success.value)

    def test_each_failure_type_fails_even_when_other_counts_unknown(self):
        for name in ("failed", "errors", "unexpected_successes"):
            with self.subTest(name=name):
                self.assertEqual(suite(**{name: 1}).status, "failed")
                self.assertEqual(TestEvidence(**{name: 1}).status, "failed")
        self.assertEqual(suite(passed=0, expected_failures=2).status, "passed")
        self.assertEqual(suite(passed=0, expected_failures=2).success.value, 0.0)


class BenchmarkEvidenceTests(unittest.TestCase):
    def test_metrics_have_independent_denominators(self):
        value = benchmark()
        self.assertEqual(value.status, "measured")
        expected = {"recovery": (8, 10), "completeness": (5, 10),
                    "wrong": (3, 9), "false_verified": (2, 6), "crashes": (0, 4)}
        for name, (numerator, denominator) in expected.items():
            with self.subTest(name=name):
                metric = value.to_dict()["measurements"][name]
                self.assertEqual(metric["numerator"], numerator)
                self.assertEqual(metric["denominator"], denominator)
                self.assertEqual(metric["value"], numerator / denominator)

    def test_wrong_unexpected_records_may_exceed_expected_records(self):
        value = benchmark(expected_records=1, recovered_records=1, complete_records=0,
                          assessed_records=5, assessed_verified_records=5,
                          wrong_records=5, false_verified_records=5)
        self.assertEqual(value.measurements["wrong"].value, 1.0)
        self.assertEqual(value.measurements["recovery"].value, 1.0)
        self.assertEqual(value.measurements["completeness"].value, 0.0)

    def test_no_ground_truth_keeps_accuracy_unknown_even_with_successful_cases(self):
        value = BenchmarkEvidence(cases=4, crashes=0)
        self.assertEqual(value.status, "measured")
        for name in ("recovery", "completeness", "wrong", "false_verified"):
            self.assertIsNone(value.measurements[name].value)
        with self.assertRaisesRegex(ValueError, "unknown"):
            BenchmarkEvidence(expected_records=0)

    def test_old_ledger_counts_do_not_fabricate_assessment_denominators(self):
        value = benchmark(assessed_records=None, assessed_verified_records=None)
        self.assertEqual(value.wrong_records, 3)
        self.assertEqual(value.false_verified_records, 2)
        self.assertIsNone(value.measurements["wrong"].value)
        self.assertIsNone(value.measurements["false_verified"].value)

    def test_zero_expected_and_zero_verified_have_unavailable_rates(self):
        value = benchmark(expected_records=0, recovered_records=0, complete_records=0,
                          assessed_records=0, assessed_verified_records=0,
                          wrong_records=0, false_verified_records=0)
        for name in ("recovery", "completeness", "wrong", "false_verified"):
            self.assertIsNone(value.measurements[name].value)

    def test_empty_missing_and_crashing_benchmarks(self):
        for value in (BenchmarkEvidence(), BenchmarkEvidence(cases=0, crashes=0),
                      BenchmarkEvidence(cases=1),
                      benchmark(resources=(Resource("samples", False),))):
            self.assertEqual(value.status, "unavailable")
        self.assertEqual(benchmark(crashes=1).status, "failed")
        self.assertEqual(benchmark(crashes=1).measurements["crashes"].value, 0.25)

    def test_impossible_counts_and_mixed_baselines_rejected(self):
        for changes in ({"baseline": "mixed"}, {"crashes": 5},
                        {"recovered_records": 11}, {"complete_records": 9},
                        {"wrong_records": 10}, {"false_verified_records": 4},
                        {"assessed_verified_records": 10}, {"assessed_records": 7},
                        {"expected_records": -1}, {"cases": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    benchmark(**changes)

    def test_baselines_remain_separate_in_saved_evidence(self):
        independent = benchmark()
        regression = benchmark(baseline="regression_baseline")
        saved = ValidationEvidence(benchmarks=(independent, regression)).to_dict()
        self.assertEqual([b["baseline"] for b in saved["benchmarks"]],
                         ["organizer_reference", "regression_baseline"])
        self.assertNotIn("accuracy", saved)
        self.assertNotIn("summary", saved)


class SerializationAndProvenanceTests(unittest.TestCase):
    def test_unknown_context_stays_unknown(self):
        saved = ReferenceEvidence().to_dict()["context"]
        self.assertIsNone(saved["app_version"])
        self.assertIsNone(saved["commit"])
        self.assertIsNone(saved["dataset"]["sha256"])
        self.assertIsNone(saved["environment"]["python_version"])
        self.assertEqual(saved["provenance"], "unknown")

    def test_live_and_historical_metadata_survive_json_round_trip(self):
        context = Context(app_version="test-version", commit="recorded-commit",
                          dataset=Dataset("known fixture set", "a" * 64),
                          environment=Environment("3.12.0", "recorded-platform"),
                          provenance="historical", recorded_at="2026-01-01T00:00:00Z",
                          source="older-evidence.json")
        historical = ReferenceEvidence(context=context, matched=7, total=7,
            resources=(Resource("references", True),),
            artifacts=(Artifact("actual", "actual/s01.dat.json", "b" * 64),))
        live = benchmark(context=Context(provenance="live"))
        evidence = ValidationEvidence(reference=historical, tests=suite(), benchmarks=(live,))
        encoded = json.dumps(evidence.to_dict(), allow_nan=False)
        restored = ValidationEvidence.from_dict(json.loads(encoded))
        self.assertEqual(restored, evidence)
        self.assertEqual(restored.reference.context.environment.platform, "recorded-platform")
        self.assertEqual(restored.reference.context.provenance, "historical")
        self.assertEqual(restored.benchmarks[0].context.provenance, "live")

    def test_missing_sections_and_empty_runs_cannot_appear_passing(self):
        empty = ValidationEvidence()
        self.assertEqual(empty.status, "unavailable")
        self.assertIsNone(empty.to_dict()["reference"])
        self.assertIsNone(empty.to_dict()["tests"])
        self.assertEqual(ValidationEvidence(tests=suite()).status, "complete")
        self.assertEqual(ValidationEvidence(tests=suite(), reference=ReferenceEvidence()).status,
                         "unavailable")
        self.assertEqual(ValidationEvidence(tests=suite(errors=1)).status, "failed")
        self.assertEqual(ValidationEvidence(benchmarks=(benchmark(),)).status, "complete")

    def test_serialization_does_not_expose_mutable_model_state(self):
        evidence = ValidationEvidence(reference=ReferenceEvidence(matched=1, total=1))
        saved = evidence.to_dict()
        saved["reference"]["matched"] = 0
        self.assertEqual(evidence.reference.matched, 1)
        with self.assertRaises(FrozenInstanceError):
            evidence.reference.matched = 0

    def test_untrusted_saved_statuses_and_rates_are_recomputed_or_rejected(self):
        for mutate in (
            lambda doc: doc.update(status="passed"),
            lambda doc: doc["reference"].update(status="passed"),
            lambda doc: doc["reference"]["agreement"].update(value=1.0),
            lambda doc: doc.update(schema_version=2),
            lambda doc: doc.update(schema_version=True),
            lambda doc: doc.update(unknown="ignored"),
            lambda doc: doc["reference"].update(total=-1),
            lambda doc: doc["reference"]["context"].update(unknown="ignored"),
        ):
            saved = ValidationEvidence(reference=ReferenceEvidence(matched=0, total=1)).to_dict()
            mutate(saved)
            with self.subTest(saved=saved):
                with self.assertRaises(ValueError):
                    ValidationEvidence.from_dict(saved)

    def test_minimal_saved_counts_recalculate_derived_fields(self):
        restored = ValidationEvidence.from_dict({"schema_version": 1,
            "reference": {"matched": 7, "total": 7, "context": {"provenance": "historical"}}})
        self.assertEqual(restored.reference.status, "passed")
        self.assertEqual(restored.reference.agreement.value, 1.0)
        self.assertIsNone(restored.tests)
        for bad in ({}, [], {"schema_version": 1, "benchmarks": {}},
                    {"schema_version": 1, "reference": []}):
            with self.assertRaises(ValueError):
                ValidationEvidence.from_dict(bad)

    def test_invalid_metadata_and_resources_are_rejected(self):
        for factory in (lambda: Context(provenance="fresh"), lambda: Dataset(sha256="unknown"),
                        lambda: Resource("samples", available=1), lambda: Artifact("actual", ""),
                        lambda: ReferenceEvidence(resources=[Resource("samples", True)]),
                        lambda: Context(dataset=None), lambda: ValidationEvidence(benchmarks=[benchmark()])):
            with self.assertRaises(ValueError):
                factory()


if __name__ == "__main__":
    unittest.main()
