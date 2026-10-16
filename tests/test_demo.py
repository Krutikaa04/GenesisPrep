"""Small deterministic fixture for the mentor walkthrough and stream behavior."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deadbits import diagnostics
from deadbits.demo import run_demo
from deadbits.validation.model import Context, Environment, TestEvidence, ValidationEvidence
from test_fmt_libra98 import KNOWN_RECORDS, known_file


ROOT = Path(__file__).resolve().parents[1]


class Interactive(io.StringIO):
    def isatty(self):
        return True


class NoInput(io.StringIO):
    def readline(self, *args):
        raise AssertionError("noninteractive demo attempted to read input")


class MentorDemo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.kit = self.root / "kit with spaces"
        self.samples = self.kit / "samples"
        self.expected = self.kit / "expected_outputs"
        self.samples.mkdir(parents=True)
        self.expected.mkdir()
        (self.samples / "circulation.bin").write_bytes(known_file())
        (self.expected / "circulation.json").write_text(json.dumps(dict(
            file="circulation.bin", format="LIBRA-98", status="ok", match_on=["id"],
            metadata={}, records=KNOWN_RECORDS)), encoding="utf-8")
        self.source = self.root / "tiny source kit"
        (self.source / "tests").mkdir(parents=True)
        (self.source / "tools").mkdir()
        (self.source / "tests/test_tiny.py").write_text(
            "import unittest\nclass Tiny(unittest.TestCase):\n    def test_ok(self): self.assertEqual(2+2,4)\n")
        for name in ("evaluate.py", "make_variants.py"):
            (self.source / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
        self.output = self.root / "mentor proof"
        self.stream = io.StringIO()

    def demo(self, **changes):
        options = dict(kit_dir=self.kit, output_dir=self.output, source_dir=self.source,
                       stream=self.stream, input_stream=NoInput())
        options.update(changes)
        return run_demo(**options)

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}

    def test_live_walkthrough_shows_actual_fields_damage_and_saved_evidence(self):
        before = self.snapshot(self.kit), self.snapshot(self.source)
        manifest = self.demo()
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual([step["status"] for step in manifest["recovery"]], ["complete"] * 4)
        self.assertEqual(before, (self.snapshot(self.kit), self.snapshot(self.source)))
        normal = json.loads((self.output / "recovered/normal.dat.json").read_text(encoding="utf-8"))
        self.assertEqual(normal["records"], KNOWN_RECORDS)
        for name, kind in (("truncation", "truncated"), ("checksum", "checksum_mismatch")):
            doc = json.loads((self.output / ("recovered/" + name + ".dat.json")).read_text(encoding="utf-8"))
            self.assertTrue(any(d["kind"] == kind for d in doc["damage"]))
            self.assertTrue(any(r.get("verified") is False for r in doc["records"]))
            self.assertTrue(all(0 <= d["offset"] <= (self.output / ("inputs/" + name + ".dat")).stat().st_size
                                for d in doc["damage"]))
        unknown = json.loads((self.output / "recovered/unknown.dat.json").read_text())
        self.assertEqual((unknown["format"], unknown["status"]), ("UNKNOWN", "unrecognized"))
        transcript = self.stream.getvalue()
        for expected in ("ASCII survives", "Unverified record:", "Damage at byte", "checksum_mismatch",
                         "Recovered fields:", "Evidence file:", "Tests: passed", "live"):
            self.assertIn(expected, transcript)
        self.assertNotIn("Press Enter", transcript)
        self.assertEqual((self.output / "transcript.txt").read_text(encoding="utf-8"), transcript)
        tests = next(s for s in manifest["validation"] if s["step"] == "test")
        self.assertEqual(tests["evidence"]["tests"]["passed"], 1)
        for step in manifest["validation"]:
            self.assertEqual(step["provenance"], "live")
            evidence = ValidationEvidence.from_dict(json.loads(Path(step["evidence_path"]).read_text()))
            self.assertEqual(evidence.status, "complete")
        saved = json.loads((self.output / "demo.json").read_text())
        self.assertEqual(saved, manifest)

    def test_generated_inputs_and_recovery_are_deterministic(self):
        self.demo(skip_validation=("verify", "test", "benchmark"))
        other = self.root / "second proof"
        self.demo(output_dir=other, skip_validation=("verify", "test", "benchmark"))
        self.assertEqual(self.snapshot(self.output / "inputs"), self.snapshot(other / "inputs"))
        self.assertEqual(self.snapshot(self.output / "recovered"), self.snapshot(other / "recovered"))

    def test_missing_libra_source_labels_three_cases_unavailable_and_keeps_unknown(self):
        (self.samples / "circulation.bin").unlink()
        result = self.demo(skip_validation=("verify", "test", "benchmark"))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual([s["status"] for s in result["recovery"]],
                         ["unavailable", "unavailable", "unavailable", "complete"])
        self.assertIn("healthy version-2 LIBRA-98", self.stream.getvalue())
        self.assertEqual(list((self.output / "inputs").iterdir()), [self.output / "inputs/unknown.dat"])

    def test_source_kit_not_assumed_and_skipped_steps_cannot_become_passes(self):
        result = self.demo(source_dir=None, skip_validation=("verify",))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual([s["status"] for s in result["validation"]], ["skipped", "unavailable", "unavailable"])
        self.assertIn("no measurement was run", self.stream.getvalue())
        self.assertIn("--source-dir", self.stream.getvalue())

    def test_historical_test_proof_is_preserved_and_not_rerun(self):
        history = self.root / "old tests.json"
        evidence = ValidationEvidence(tests=TestEvidence(
            context=Context(app_version="old-app", commit="old-commit", provenance="live",
                            environment=Environment("old-python", "old-platform"),
                            recorded_at="2020-01-01T00:00:00Z"),
            passed=3, failed=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0))
        history.write_text(json.dumps(evidence.to_dict()))
        before = history.read_bytes()
        with patch.object(diagnostics, "run_validation", side_effect=AssertionError("live validation executed")):
            result = self.demo(historical={"test": history}, skip_validation=("verify", "benchmark"))
        saved = next(s for s in result["validation"] if s["step"] == "test")
        self.assertEqual(saved["provenance"], "historical")
        context = saved["evidence"]["tests"]["context"]
        self.assertEqual((context["app_version"], context["commit"], context["environment"]["python_version"]),
                         ("old-app", "old-commit", "old-python"))
        self.assertEqual(context["provenance"], "historical")
        self.assertEqual(history.read_bytes(), before)
        self.assertIn("no current validation was executed", self.stream.getvalue())
        self.assertTrue(all(s["provenance"] == "live" for s in result["recovery"]))

    def test_missing_malformed_or_wrong_section_history_cannot_pass(self):
        history = self.root / "history.json"
        for contents, expected in ((None, "unavailable"), ("{bad", "failed"),
                                    ('{"schema_version": 1}', "unavailable")):
            if contents is not None:
                history.write_text(contents)
            result = self.demo(output_dir=self.root / expected / str(len(str(contents))),
                               historical={"test": history}, skip_validation=("verify", "benchmark"))
            step = next(s for s in result["validation"] if s["step"] == "test")
            self.assertEqual((step["status"], step["provenance"]), (expected, "historical"))

    def test_runner_error_is_recorded_and_other_steps_are_kept(self):
        with patch.object(diagnostics, "run_validation", side_effect=RuntimeError("known failure")):
            result = self.demo(skip_validation=("test", "benchmark"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["validation"][0]["status"], "failed")
        self.assertIn("known failure", self.stream.getvalue())
        self.assertTrue((self.output / "demo.json").exists())

    def test_guided_redirected_output_never_reads_and_tty_eof_continues(self):
        self.demo(guided=True, skip_validation=("verify", "test", "benchmark"))
        self.assertIn("Guided prompts skipped", self.stream.getvalue())
        tty = Interactive()
        self.demo(output_dir=self.root / "tty demo", stream=tty, input_stream=Interactive(""),
                  guided=True, skip_validation=("verify", "test", "benchmark"))
        self.assertEqual(tty.getvalue().count("Press Enter"), 1)
        self.assertIn("Input ended", tty.getvalue())

    def test_existing_output_and_input_roots_are_protected(self):
        for target in (self.kit, self.kit / "nested", self.source / "nested", self.root, ROOT / "demo-proof"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.demo(output_dir=target)
        self.output.mkdir()
        marker = self.output / "marker"
        marker.write_text("preserve")
        with self.assertRaises(FileExistsError):
            self.demo()
        self.assertEqual(marker.read_text(), "preserve")

    def test_unknown_validation_options_and_conflicts_are_rejected_before_writing(self):
        for options in ({"skip_validation": ("bogus",)}, {"historical": {"bogus": "path"}},
                        {"historical": {"test": "old"}, "skip_validation": ("test",)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.demo(**options)
        self.assertFalse(self.output.exists())

    def test_cli_redirected_run_is_noninteractive_and_saves_manifest(self):
        command = [sys.executable, "-m", "deadbits.demo", "--kit-dir", str(self.kit),
                   "--output-dir", str(self.output), "--source-dir", str(self.source), "--guided"]
        result = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Guided prompts skipped", result.stdout)
        self.assertIn("Demo: complete", result.stdout)
        self.assertEqual(self.snapshot(self.kit)["samples/circulation.bin"], hashlib.sha256(known_file()).hexdigest())
        self.assertTrue((self.output / "demo.json").exists())
        invalid = subprocess.run(command + ["--historical-evidence", "test=old.json", "--skip-validation", "test"],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, encoding="utf-8", timeout=10)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("both historical and skipped", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
