"""Known-answer denominator checks and equivalence with the original evaluator."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from deadbits import cli, diagnostics
from deadbits.validation.benchmark import _assessment_counts, _load_scorer, run_benchmark
from deadbits.validation.model import ValidationEvidence


ROOT = Path(__file__).resolve().parents[1]


def archive(name="a", digest="abc", **extra):
    return dict(name=name, offset=12, size=3, sha256=digest, **extra)


def document(records=(), fmt="PAK", status="ok"):
    return dict(format=fmt, status=status, records=list(records))


class BenchmarkRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.samples = self.root / "samples & offline"
        self.expected = self.root / "expected"
        self.samples.mkdir()
        self.expected.mkdir()
        self.scorer = _load_scorer(ROOT)

    def seed(self):
        for name, data in (("ref", b"original"), ("reg", b"original"), ("empty", b"")):
            (self.samples / name).write_bytes(data)
        (self.expected / "ref.json").write_text(json.dumps(dict(
            file="ref", format="PAK", match_on=["name"], records=[archive()])))

    @staticmethod
    def decoder(data, name):
        if name == "empty":
            return document([], "UNKNOWN", "unrecognized")
        if data == b"original":
            return document([archive()])
        return document([archive(digest="wrong"), archive("unexpected", verified=False)])

    def run_benchmark(self, **changes):
        options = dict(source_dir=ROOT, samples_dir=self.samples, expected_dir=self.expected,
                       decoder=self.decoder, output_dir=self.root / "evidence")
        options.update(changes)
        return run_benchmark(**options)

    def read(self, name, output="evidence"):
        return json.loads((self.root / output / name).read_text(encoding="utf-8"))

    def test_original_counts_and_rates_match_and_baselines_never_mix(self):
        self.seed()
        old = self.scorer.evaluate(self.samples, self.expected, self.decoder)
        evidence = self.run_benchmark()
        ledger = self.read("cases.json")
        self.assertEqual([{key: case[key] for key in old["cases"][i]}
                          for i, case in enumerate(ledger["cases"])], old["cases"])
        self.assertEqual(ledger["baselines"], old["baselines"])
        summary = self.read("summary.json")
        self.assertNotIn("summary", summary)
        self.assertEqual((summary["variants"], summary["changed_variants"], summary["unchanged_variants"]), (18, 12, 6))
        old_rows = {(r["baseline"], r["format"]): r for r in old["by_format"]}
        for row in evidence.benchmarks:
            original = old_rows[row.baseline, row.format]
            self.assertEqual(row.cases, original["cases"])
            self.assertEqual(row.crashes, original["crashes"])
            if row.baseline == "no_record_baseline":
                self.assertIsNone(row.expected_records)
                self.assertIsNone(row.measurements["wrong"].value)
                self.assertEqual(row.status, "unavailable")  # all its mutations were no-ops
                continue
            self.assertEqual(row.measurements["recovery"].value, original["record_recovery_rate"])
            self.assertEqual(row.measurements["completeness"].value, original["complete_record_rate"])
            self.assertEqual((row.recovered_records, row.wrong_records, row.false_verified_records), (6, 12, 6))
            self.assertEqual((row.assessed_records, row.assessed_verified_records), (12, 6))
            self.assertEqual(row.measurements["wrong"].value, 1.0)
            self.assertEqual(row.measurements["false_verified"].value, 1.0)
        for row in summary["rows"]:
            self.assertEqual(row["detection_coverage"]["value"], old_rows[row["baseline"], row["format"]]["format_coverage_rate"])
        self.assertEqual({row.baseline for row in evidence.benchmarks},
                         {"organizer_reference", "regression_baseline", "no_record_baseline"})

    def test_assessment_denominators_reuse_matching_for_partial_and_duplicate_records(self):
        baseline = self.scorer.make_baseline(document([archive(), archive("optional", verified=False)], status="partial"))
        actual = document([archive(verified=False), archive(), archive("optional"), archive("novel")])
        counts = self.scorer.compare_records(actual, baseline)
        self.assertEqual(_assessment_counts(actual, baseline, counts, self.scorer), (1, 0))
        actual["records"].reverse()
        counts = self.scorer.compare_records(actual, baseline)
        self.assertEqual(_assessment_counts(actual, baseline, counts, self.scorer), (1, 1))

    def test_exhaustive_truth_excludes_optional_but_assesses_unexpected_outputs(self):
        expected = dict(format="PAK", match_on=["name"], records=[archive()],
                        optional_partial_records=[dict(name="optional")])
        baseline = self.scorer.make_baseline(document([]), expected)
        actual = document([archive(verified=False), archive(), archive("optional"), {"verified": True}])
        counts = self.scorer.compare_records(actual, baseline)
        self.assertEqual(_assessment_counts(actual, baseline, counts, self.scorer), (3, 2))

    def test_artifact_hashes_dataset_manifest_and_schema_round_trip(self):
        self.seed()
        evidence = self.run_benchmark(commit="explicit-measured-commit")
        self.assertEqual(ValidationEvidence.from_dict(evidence.to_dict()), evidence)
        manifest = self.read("dataset.json")
        payload = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(manifest["sha256"], digest)
        for row in evidence.benchmarks:
            self.assertEqual(row.context.dataset.sha256, digest)
            self.assertEqual(row.context.commit, "explicit-measured-commit")
            self.assertEqual(row.context.provenance, "live")
            for artifact in row.artifacts:
                self.assertEqual(artifact.sha256, hashlib.sha256((self.root / "evidence" / artifact.path).read_bytes()).hexdigest())
        self.assertIn("scoring/evaluate.py", [item["path"] for item in manifest["files"]])
        (self.samples / "reg").write_bytes(b"changed")
        other = self.run_benchmark(output_dir=self.root / "other")
        self.assertNotEqual(other.benchmarks[0].context.dataset.sha256, digest)

    def test_persisted_corpus_equivalence_and_tamper_rejection(self):
        self.seed()
        from test_evaluate import create_corpus
        corpus = self.root / "variants"
        create_corpus(self.samples, corpus)
        old = self.scorer.evaluate(self.samples, self.expected, self.decoder, corpus)
        self.run_benchmark(corpus_dir=corpus)
        ledger = self.read("cases.json")["cases"]
        self.assertEqual([{k: row[k] for k in old["cases"][i]} for i, row in enumerate(ledger)], old["cases"])
        manifest = json.loads((corpus / "manifest.json").read_text())
        (corpus / manifest["variants"][0]["file"]).write_bytes(b"tampered")
        evidence = self.run_benchmark(corpus_dir=corpus, output_dir=self.root / "tampered")
        self.assertEqual(evidence.status, "unavailable")
        self.assertIsNone(evidence.benchmarks[0].cases)
        self.assertIn("deterministic mutation", self.read("summary.json", "tampered")["problem"])

    def test_missing_resources_empty_inputs_and_absent_truth_never_look_accurate(self):
        for options in ({"samples_dir": None}, {"expected_dir": self.root / "missing"},
                        {"source_dir": self.root / "portable"}, {"corpus_dir": self.root / "missing"}):
            with self.subTest(options=options):
                evidence = self.run_benchmark(output_dir=None, **options)
                self.assertEqual(evidence.status, "unavailable")
                self.assertIsNone(evidence.benchmarks[0].measurements["recovery"].value)
        empty = self.run_benchmark()
        self.assertEqual(empty.status, "unavailable")
        self.assertIsNone(empty.benchmarks[0].cases)
        (self.samples / "reg").write_bytes(b"original")
        regression = self.run_benchmark(output_dir=None)
        self.assertEqual([r.baseline for r in regression.benchmarks], ["regression_baseline"])
        unknown = self.run_benchmark(output_dir=None,
            decoder=lambda data, name: document([], "UNKNOWN", "unrecognized"))
        row = unknown.benchmarks[0]
        self.assertEqual((row.baseline, row.status), ("no_record_baseline", "measured"))
        for name in ("recovery", "completeness", "wrong", "false_verified"):
            self.assertIsNone(row.measurements[name].value)

    def test_variant_crashes_and_baseline_crashes_are_separate(self):
        (self.samples / "reg").write_bytes(b"original")
        def broken(data, name):
            if data == b"original":
                return document([archive()])
            raise RuntimeError("decoder crash")
        evidence = self.run_benchmark(decoder=broken)
        row = evidence.benchmarks[0]
        self.assertEqual((row.status, row.crashes, row.cases), ("failed", 6, 6))
        self.assertEqual(row.measurements["crashes"].value, 1.0)
        self.assertEqual(self.read("summary.json")["baseline_crashes"]["numerator"], 0)
        def original_only_crash(data, name):
            if data == b"original":
                raise ValueError("original crash")
            return document([])
        evidence = self.run_benchmark(decoder=original_only_crash, output_dir=self.root / "original_crash")
        self.assertEqual(evidence.status, "unavailable")
        self.assertEqual(self.read("summary.json", "original_crash")["baseline_crashes"]["value"], 1.0)

    def test_engine_caught_exceptions_remain_crashes_through_the_adapter(self):
        (self.samples / "reg").write_bytes(b"original")
        class Caught:
            notes = ["decoder exception: ValueError"]

            def to_dict(self):
                return document([], status="failed")

        def decoder(data, name):
            return document([archive()]) if data == b"original" else Caught()

        row = self.run_benchmark(decoder=decoder).benchmarks[0]
        self.assertEqual((row.status, row.crashes, row.cases), ("failed", 6, 6))

    def test_malformed_references_do_not_produce_partial_passing_metrics(self):
        (self.samples / "reg").write_bytes(b"original")
        (self.expected / "bad.json").write_text("{malformed")
        evidence = self.run_benchmark()
        self.assertEqual(evidence.status, "unavailable")
        self.assertIsNone(evidence.benchmarks[0].cases)
        self.assertIn("JSONDecodeError", self.read("summary.json")["problem"])

    def test_input_changes_during_execution_invalidate_dataset_and_measurement(self):
        (self.samples / "reg").write_bytes(b"original")
        def mutating(data, name):
            (self.samples / "reg").write_bytes(b"modified input")
            return document([archive()])
        evidence = self.run_benchmark(decoder=mutating)
        self.assertEqual(evidence.status, "unavailable")
        self.assertIsNone(evidence.benchmarks[0].context.dataset.sha256)
        self.assertIn("changed during execution", self.read("summary.json")["problem"])

    def test_loader_restores_global_import_state(self):
        old_path = sys.path[:]
        previous = sys.modules.get("make_variants")
        _load_scorer(ROOT)
        self.assertEqual(sys.path, old_path)
        self.assertIs(sys.modules.get("make_variants"), previous)

    def test_output_never_overwrites_inputs_or_prior_proof(self):
        self.seed()
        for target in (self.samples, self.samples / "nested", ROOT / "out", self.root):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.run_benchmark(output_dir=target)
        self.run_benchmark()
        saved = (self.root / "evidence" / "summary.json").read_bytes()
        with self.assertRaises(ValueError):
            self.run_benchmark()
        self.assertEqual((self.root / "evidence" / "summary.json").read_bytes(), saved)

    def test_existing_cli_request_boundary_and_saved_historical_evidence(self):
        self.seed()
        target = self.root / "cli proof"
        args = ["--benchmark", "--source-dir", str(ROOT), "--samples-dir", str(self.samples),
                "--expected-dir", str(self.expected), "--evidence-dir", str(target)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        # The real decoder leaves the synthetic bytes unknown; the explicit
        # reference still supplies independent PAK truth for one source.
        self.assertEqual(code, 0, err.getvalue())
        self.assertTrue((target / "validation.json").is_file(), err.getvalue())
        loaded = diagnostics.load_evidence(target / "validation.json", "benchmark")
        self.assertTrue(all(row.context.provenance == "historical" for row in loaded.benchmarks))
        self.assertIn("organizer_reference", out.getvalue())
        self.assertIn("no_record_baseline", out.getvalue())

    def test_official_corpus_equivalence_on_current_decoder(self):
        samples, refs = ROOT / "samples/official/samples", ROOT / "samples/official/expected_outputs"
        old = self.scorer.evaluate(samples, refs)
        evidence = self.run_benchmark(samples_dir=samples, expected_dir=refs, decoder=self.scorer.salvage_bytes)
        cases = self.read("cases.json")["cases"]
        self.assertEqual([{k: row[k] for k in old["cases"][i]} for i, row in enumerate(cases)], old["cases"])
        rows = {(row.baseline, row.format): row for row in evidence.benchmarks}
        for original in old["by_format"]:
            row = rows[original["baseline"], original["format"]]
            self.assertEqual((row.cases, row.crashes), (original["cases"], original["crashes"]))
            if row.baseline != "no_record_baseline":
                self.assertEqual((row.recovered_records, row.complete_records, row.wrong_records, row.false_verified_records),
                    tuple(original[k] for k in ("recovered_records", "correct_records", "wrong_records", "false_verified_records")))
                self.assertEqual(row.measurements["recovery"].value, original["record_recovery_rate"])


if __name__ == "__main__":
    unittest.main()
