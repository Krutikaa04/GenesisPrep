"""Release artifacts are reproducible snapshots, not working-tree bundles."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_release", ROOT / "tools/build_release.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def release_files():
    files = {path.relative_to(ROOT).as_posix(): (path.read_bytes(), 0o644)
             for path in (ROOT / "deadbits").rglob("*.py") if "__pycache__" not in path.parts}
    files["deadbits/version.py"] = (b'VERSION = "0.1.0"\n', 0o644)
    files["tools/release_installer.py"] = ((ROOT / "tools/release_installer.py").read_bytes(), 0o644)
    files["docs/INSTALL.md"] = (b"Offline installation requires Python 3.10+.\n", 0o644)
    return files


class ReleasePackagingTests(unittest.TestCase):
    def test_deterministic_artifacts_checksums_and_version(self):
        files = release_files()
        first = build.artifacts("a" * 40, files)
        self.assertEqual(first, build.artifacts("a" * 40, dict(reversed(list(files.items())))))
        manifest = json.loads(first["release-manifest.json"])
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["commit"], "a" * 40)
        for name, entry in manifest["artifacts"].items():
            self.assertEqual(entry["sha256"], hashlib.sha256(first[name]).hexdigest())
            self.assertEqual(entry["bytes"], len(first[name]))
        for line in first["SHA256SUMS"].decode().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256(first[name]).hexdigest())
        with self.assertRaisesRegex(ValueError, "committed VERSION"):
            build.artifacts("a" * 40, files, "1.0.0")

    def test_application_includes_only_python_and_all_adapters(self):
        files = release_files()
        files["deadbits/__pycache__/foreign.py"] = (b"bad", 0o644)
        files["secrets.env"] = (b"not shipped", 0o600)
        files["deadbits/credential.txt"] = (b"not shipped", 0o600)
        result = build.artifacts("a" * 40, files)
        with zipfile.ZipFile(io.BytesIO(result["salvage-0.1.0.pyz"])) as archive:
            names = archive.namelist()
            self.assertIn("__main__.py", names)
            self.assertTrue(all(name.endswith(".py") for name in names))
            self.assertFalse(any("__pycache__" in name for name in names))
            expected = {"bravo", "cvt", "ebcdic_dump", "lablog", "libra98", "pak", "vault", "wad", "wks", "wpd"}
            actual = {Path(name).stem for name in names
                      if name.startswith("deadbits/formats/") and not Path(name).stem.startswith("_")}
            self.assertEqual(actual, expected)
        with zipfile.ZipFile(io.BytesIO(result["salvage-0.1.0-installer.zip"])) as archive:
            self.assertEqual(set(archive.namelist()), {"salvage.pyz", "install.py", "INSTALL.md", "SHA256SUMS"})
            self.assertEqual(archive.read("salvage.pyz"), result["salvage-0.1.0.pyz"])

    def test_wrapper_checks_python_before_importing_application(self):
        code = ("import sys; sys.version_info=(3,9); "
                "exec(" + repr(build.MAIN.decode("utf-8")) + ")")
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Python 3.10", result.stderr)
        self.assertNotIn("ImportError", result.stderr)

    @unittest.skipUnless(shutil.which("git"), "Git is required to verify committed source snapshots")
    def test_snapshot_excludes_untracked_and_rejects_dirty_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            git = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
            git("init")
            git("config", "user.name", "Release test")
            git("config", "user.email", "release-test@example.invalid")
            (repo / "samples/official").mkdir(parents=True)
            fixture = b"official bytes\x00\xff"
            (repo / "samples/official/fixture.dat").write_bytes(fixture)
            (repo / "salvage").write_bytes(b"#!/bin/sh\n")
            (repo / "salvage").chmod(0o755)
            git("add", ".")
            git("commit", "-m", "Test snapshot")
            (repo / "secret.env").write_bytes(b"do not package")
            (repo / "__pycache__").mkdir()
            (repo / "__pycache__/cache.pyc").write_bytes(b"cache")
            commit, files = build.snapshot(repo)
            self.assertEqual(len(commit), 40)
            self.assertEqual(set(files), {"salvage", "samples/official/fixture.dat"})
            self.assertEqual(files["samples/official/fixture.dat"][0], fixture)
            if __import__("os").name != "nt":
                self.assertEqual(files["salvage"][1], 0o755)
            (repo / "salvage").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "commit tracked changes"):
                build.snapshot(repo)

    @unittest.skipUnless(shutil.which("git"), "Git is required to verify committed source snapshots")
    def test_snapshot_uses_raw_blobs_despite_checkout_and_archive_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            git = lambda *args: subprocess.run(["git", "-C", str(repo), *args],
                                               check=True, capture_output=True).stdout
            git("init")
            git("config", "user.name", "Release test")
            git("config", "user.email", "release-test@example.invalid")
            git("config", "core.autocrlf", "false")
            (repo / ".gitattributes").write_bytes(b"ignored.txt export-ignore\nversion.txt export-subst\n")
            (repo / "lines.txt").write_bytes(b"one\ntwo\n")
            (repo / "ignored.txt").write_bytes(b"tracked and required\n")
            (repo / "version.txt").write_bytes(b"$Format:%H$\n")
            git("add", ".")
            git("commit", "-m", "Raw snapshot fixture")
            commit, canonical = build.snapshot(repo)
            git("config", "core.autocrlf", "true")
            git("config", "core.eol", "crlf")
            for name in ("lines.txt", "ignored.txt", "version.txt", ".gitattributes"):
                (repo / name).unlink()
            git("checkout", "--", ".")
            self.assertEqual((repo / "lines.txt").read_bytes(), b"one\r\ntwo\r\n")
            other_commit, windows_settings = build.snapshot(repo)
            self.assertEqual(other_commit, commit)
            self.assertEqual(windows_settings, canonical)
            self.assertEqual(windows_settings["lines.txt"][0], b"one\ntwo\n")
            self.assertEqual(windows_settings["version.txt"][0], b"$Format:%H$\n")
            self.assertIn("ignored.txt", windows_settings)

    def test_source_archive_retains_exact_tracked_content_and_modes(self):
        files = release_files()
        files["salvage"] = (b"#!/bin/sh\n", 0o755)
        files["samples/official/example.bin"] = (b"\x00\xff", 0o644)
        result = build.artifacts("a" * 40, files)
        with zipfile.ZipFile(io.BytesIO(result["salvage-0.1.0-source.zip"])) as archive:
            self.assertEqual(len(archive.namelist()), len(files))
            for name, (data, mode) in files.items():
                member = "salvage-0.1.0/" + name
                self.assertEqual(archive.read(member), data)
                self.assertEqual((archive.getinfo(member).external_attr >> 16) & 0o777, mode)
                self.assertEqual(archive.getinfo(member).date_time, (1980, 1, 1, 0, 0, 0))
