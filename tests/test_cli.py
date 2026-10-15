"""CLI contract: naming, non-recursion, report.json, exit code, determinism, hostile directories."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, SAMPLES, STATUSES, KINDS


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
