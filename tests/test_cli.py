"""CLI contract: naming, non-recursion, report.json, exit code, determinism, hostile directories."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import CAN_SYMLINK, ROOT, SAMPLES, STATUSES, KINDS, SYMLINK_SKIP_REASON


def _bash_works() -> bool:
    exe = shutil.which("bash")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "-c", "echo $OSTYPE"], capture_output=True, text=True, timeout=20).stdout.strip()
        # on Windows only Git-Bash/MSYS understands C:/ paths (WSL's bash.exe would not)
        return bool(out) and (os.name != "nt" or out.startswith(("msys", "cygwin")))
    except Exception:  # noqa: BLE001
        return False


def run_cli(src, dst, cwd=None):
    p = subprocess.run([sys.executable, "-m", "deadbits.cli", str(src), str(dst)], cwd=cwd or ROOT,
                       capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(ROOT)))
    return p.returncode, p.stdout, p.stderr


class Cli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        t = Path(cls.tmp.name)
        cls.inp, cls.out = t / "in", t / "out"
        shutil.copytree(SAMPLES, cls.inp)          # includes nested/readme_ignore.txt
        (cls.inp / "dir_named_like_file.dat").mkdir()
        (cls.inp / "dir_named_like_file.dat" / "inner.dat").write_bytes(b"LB98" + bytes(40))
        (cls.inp / "weird name (1) é.dat").write_bytes((SAMPLES / "s01.dat").read_bytes())
        cls.names = sorted(p.name for p in cls.inp.iterdir() if p.is_file())
        cls.rc, cls.stdout, cls.stderr = run_cli(cls.inp, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exit_zero(self):
        self.assertEqual(self.rc, 0, self.stderr)

    def test_one_json_per_file_named_with_full_input_name(self):
        outs = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(outs, sorted([n + ".json" for n in self.names] + ["report.json"]))
        self.assertIn("s01.dat.json", outs)
        self.assertIn("s29_almost_libra.dat.json", outs)

    def test_directories_and_nested_files_skipped(self):
        outs = {p.name for p in self.out.iterdir()}
        self.assertNotIn("readme_ignore.txt.json", outs)
        self.assertNotIn("inner.dat.json", outs)
        self.assertNotIn("dir_named_like_file.dat.json", outs)

    def test_per_file_shape(self):
        for n in self.names:
            d = json.loads((self.out / (n + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(set(d), {"source_file", "format", "status", "metadata", "records", "damage"}, n)
            self.assertEqual(d["source_file"], n)
            self.assertIn(d["status"], STATUSES)
            for dm in d["damage"]:
                self.assertEqual(set(dm), {"kind", "offset", "detail", "lossy"})
                self.assertIn(dm["kind"], KINDS)

    def test_report_json(self):
        r = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        self.assertIn("tool_version", r)
        self.assertEqual([f["file"] for f in r["files"]], self.names)         # sorted, deterministic
        self.assertEqual(sum(r["totals"].values()), len(self.names))
        for f in r["files"]:
            d = json.loads((self.out / (f["file"] + ".json")).read_text(encoding="utf-8"))
            self.assertEqual((f["format"], f["status"], f["records"], f["damage"]),
                             (d["format"], d["status"], len(d["records"]), len(d["damage"])))
        self.assertEqual(r["totals"]["unrecognized"], 5)

    def test_deterministic(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as o2:
            run_cli(self.inp, o2)
            for p in self.out.iterdir():
                self.assertEqual(p.read_bytes(), (Path(o2) / p.name).read_bytes(), p.name)

    def test_lf_only_output(self):
        self.assertNotIn(b"\r\n", (self.out / "s01.dat.json").read_bytes())

    def test_relative_paths_and_cwd_independence(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            rc, _, err = run_cli("in", "out", cwd=None) if False else (None, None, None)
            shutil.copytree(self.inp, Path(t) / "in")
            p = subprocess.run([sys.executable, "-m", "deadbits.cli", "in", "out"], cwd=t, capture_output=True,
                               text=True, env=dict(os.environ, PYTHONPATH=str(ROOT)))
            self.assertEqual(p.returncode, 0)
            self.assertTrue((Path(t) / "out" / "report.json").exists())

    def test_missing_input_and_bad_usage_still_exit_zero(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            rc, _, _ = run_cli(Path(t) / "nope", Path(t) / "o")
            self.assertEqual(rc, 0)
            self.assertTrue((Path(t) / "o" / "report.json").exists())
        p = subprocess.run([sys.executable, "-m", "deadbits.cli"], cwd=ROOT, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=str(ROOT)))
        self.assertEqual(p.returncode, 0)

    def test_empty_input_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            (Path(t) / "in").mkdir()
            rc, _, _ = run_cli(Path(t) / "in", Path(t) / "out")
            self.assertEqual(rc, 0)
            r = json.loads((Path(t) / "out" / "report.json").read_text())
            self.assertEqual(r["files"], [])

    @unittest.skipUnless(_bash_works(), "a working bash is not available (e.g. WSL stub without a distro)")
    def test_bash_launcher(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            launcher = (ROOT / "salvage").as_posix()
            p = subprocess.run([shutil.which("bash"), launcher, str(self.inp), str(Path(t) / "o")], cwd=t,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue((Path(t) / "o" / "s01.dat.json").exists())


if __name__ == "__main__":
    unittest.main()


class CliSafety(unittest.TestCase):
    def test_report_shape_on_missing_input(self):
        from deadbits.cli import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = run(root / "missing", root / "out")
            self.assertEqual(set(report), {"tool_version", "files", "totals"})

    def test_same_directory_does_not_overwrite_inputs(self):
        from deadbits.cli import main
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            source.write_bytes(b"precious source bytes")
            self.assertEqual(main([directory, directory]), 0)
            self.assertEqual(source.read_bytes(), b"precious source bytes")

    @unittest.skipUnless(CAN_SYMLINK, SYMLINK_SKIP_REASON)
    def test_symlinks_are_failed_and_output_symlinks_are_replaced_safely(self):
        from deadbits.cli import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            out.mkdir()
            (inp / "good").write_bytes((SAMPLES / "s01.dat").read_bytes())
            (inp / "link").symlink_to(inp / "good")
            (inp / "dirlink").symlink_to(out, target_is_directory=True)
            outside = root / "outside"
            outside.write_bytes(b"do not overwrite")
            (out / "good.json").symlink_to(outside)
            (out / "report.json").symlink_to(outside)
            report = run(inp, out)
            self.assertEqual(outside.read_bytes(), b"do not overwrite")
            self.assertFalse((out / "good.json").is_symlink())
            self.assertFalse((out / "report.json").is_symlink())
            rows = {row["file"]: row for row in report["files"]}
            self.assertEqual(rows["good"]["status"], "ok")
            self.assertEqual(rows["link"]["status"], "failed")
            self.assertEqual(rows["dirlink"]["status"], "failed")
            self.assertEqual(len(report["files"]), 3)

    def test_long_basename_failure_does_not_abort_siblings(self):
        from deadbits.cli import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            long_name = "a" * 255
            try:
                (inp / long_name).write_bytes(b"unknown")
            except OSError as exc:
                self.skipTest("filesystem does not support 255-byte basenames: %s" % exc)
            (inp / "z-good").write_bytes((SAMPLES / "s01.dat").read_bytes())
            report = run(inp, out)
            rows = {row["file"]: row for row in report["files"]}
            self.assertEqual(rows[long_name]["status"], "failed")
            self.assertIn("could not write", rows[long_name]["notes"][0])
            self.assertEqual(rows["z-good"]["status"], "ok")
            self.assertTrue((out / "z-good.json").exists())
            self.assertEqual(set(report), {"tool_version", "files", "totals"})

    def test_surrogate_filename_json_roundtrips_as_valid_utf8(self):
        from deadbits.cli import _dump
        name = "name-" + chr(0xdcff)
        payload = _dump({"source_file": name, "text": "caf\u00e9"})
        payload.decode("utf-8")
        self.assertEqual(json.loads(payload)["source_file"], name)
        self.assertIn("caf\u00e9".encode("utf-8"), payload)
        self.assertNotIn(b"\r\n", payload)

    @unittest.skipIf(os.name == "nt", "POSIX byte filenames only")
    def test_non_utf8_filename_end_to_end_where_supported(self):
        from deadbits.cli import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            raw_name = os.fsencode(inp) + b"/raw-\xff"
            try:
                with open(raw_name, "wb") as stream:
                    stream.write(b"unknown")
            except OSError as exc:
                self.skipTest("filesystem rejects invalid UTF-8 filenames: %s" % exc)
            report = run(inp, out)
            name = os.fsdecode(b"raw-\xff")
            self.assertEqual(report["files"][0]["file"], name)
            self.assertEqual(json.loads((out / (name + ".json")).read_bytes())["source_file"], name)

    def test_invalid_decoder_document_does_not_abort_siblings(self):
        from unittest.mock import patch
        from deadbits.cli import run
        from deadbits.engine import salvage_file
        from deadbits.model import Result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            (inp / "bad").write_bytes(b"bad")
            (inp / "good").write_bytes((SAMPLES / "s01.dat").read_bytes())
            result = Result("bad", "PAK", "ok")
            result.metadata["bad_number"] = float("nan")
            with patch("deadbits.cli.salvage_file", side_effect=lambda p: result if p.name == "bad" else salvage_file(p)):
                report = run(inp, out)
            self.assertEqual([row["status"] for row in report["files"]], ["failed", "ok"])
            self.assertTrue((out / "report.json").exists())

    def test_report_basename_collision_is_explicitly_failed(self):
        from deadbits.cli import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            (inp / "report").write_bytes(b"unknown")
            report = run(inp, out)
            self.assertEqual(report["files"][0]["status"], "failed")
            self.assertIn("collides", report["files"][0]["notes"][0])
            self.assertEqual(json.loads((out / "report.json").read_bytes()), report)

    def test_case_variant_report_names_follow_actual_filesystem_identity(self):
        from deadbits.cli import run
        for name in ("REPORT", "Report"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                inp, out = root / "in", root / "out"
                inp.mkdir()
                out.mkdir()
                probe = out / "CaseProbe"
                probe.write_bytes(b"probe")
                insensitive = (out / "caseprobe").exists()
                probe.unlink()
                (inp / name).write_bytes(b"unknown")
                report = run(inp, out)
                self.assertEqual(report["files"][0]["status"], "failed" if insensitive else "unrecognized")
                if insensitive:
                    self.assertIn("collides", report["files"][0]["notes"][0])
                else:
                    self.assertEqual(json.loads((out / (name + ".json")).read_bytes())["source_file"], name)
                self.assertEqual(json.loads((out / "report.json").read_bytes()), report)

    @unittest.skipUnless(hasattr(os, "link"), "hard links unavailable")
    def test_existing_output_alias_does_not_overwrite_an_earlier_result(self):
        from unittest.mock import patch
        from deadbits.cli import run, _write_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            (inp / "a").write_bytes(b"first")
            (inp / "b").write_bytes(b"second")
            (inp / "c").write_bytes(b"third")
            def write_with_alias(path, obj):
                _write_json(path, obj)
                if path.name == "a.json":
                    os.link(path, out / "b.json")
            with patch("deadbits.cli._write_json", side_effect=write_with_alias):
                report = run(inp, out)
            self.assertEqual([row["status"] for row in report["files"]],
                             ["unrecognized", "failed", "unrecognized"])
            self.assertIn("collides", report["files"][1]["notes"][0])
            self.assertEqual(json.loads((out / "a.json").read_bytes())["source_file"], "a")
            self.assertEqual(json.loads((out / "c.json").read_bytes())["source_file"], "c")

    @unittest.skipUnless(os.name != "nt", "POSIX executable launcher")
    def test_native_executable_launcher_from_other_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            process = subprocess.run([str(ROOT / "salvage"), str(SAMPLES), str(output)],
                                     cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue((output / "report.json").exists())
