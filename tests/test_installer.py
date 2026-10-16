"""Exercise actual installer payloads and refusal/rollback behavior offline."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from test_release_packaging import build, release_files

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_installer", ROOT / "tools/release_installer.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / "installer bundle"
        self.bundle.mkdir()
        result = build.artifacts("a" * 40, release_files())
        with zipfile.ZipFile(io.BytesIO(result["salvage-0.1.0-installer.zip"])) as archive:
            archive.extractall(self.bundle)
        self.prefix = self.root / "user tools ü and spaces"
        self.cwd = self.root / "foreign working directory"
        self.cwd.mkdir()
        self.env = os.environ.copy()
        self.env.pop("PYTHONPATH", None)
        self.env.pop("PYTHONHOME", None)
        self.launcher = self.prefix / ("bin/salvage.cmd" if os.name == "nt" else "bin/salvage")

    def run_install(self, *args, success=True, env=None):
        completed = subprocess.run([sys.executable, "-I", str(self.bundle / "install.py"),
                                    "--prefix", str(self.prefix), *args], cwd=self.cwd,
                                   env=env or self.env, capture_output=True, text=True, timeout=40)
        if success:
            self.assertEqual(completed.returncode, 0, completed.stderr)
        else:
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return completed

    def run_launcher(self, *args):
        command = [str(self.launcher), *args]
        if os.name == "nt":
            command = ["cmd.exe", "/d", "/c", str(self.launcher), *args]
        return subprocess.run(command, cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=40)

    def test_real_install_recovery_reinstall_uninstall_with_unrelated_files(self):
        installed = self.run_install()
        self.assertIn("Installed Salvage 0.1.0", installed.stdout)
        self.assertTrue(self.launcher.exists())
        incoming = self.root / "incoming files"
        incoming.mkdir()
        original = ROOT / "samples/official/samples/s01.dat"
        (incoming / "library.bin").write_bytes(original.read_bytes())
        outgoing = self.root / "recovered files"
        result = self.run_launcher(str(incoming), str(outgoing))
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads((outgoing / "library.bin.json").read_text(encoding="utf-8"))
        self.assertEqual(document["format"], "LIBRA-98")
        self.assertEqual(len(document["records"]), 5)
        self.assertEqual(document["status"], "ok")
        marker = self.prefix / "share/salvage/my-own-file.txt"
        marker.write_text("preserve me", encoding="utf-8")
        self.run_install()
        self.run_install("--uninstall")
        self.assertFalse(self.launcher.exists())
        self.assertFalse((self.prefix / "share/salvage/salvage.pyz").exists())
        self.assertEqual(marker.read_text(), "preserve me")
        self.run_install("--uninstall")

    def test_unmanaged_file_is_never_overwritten(self):
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text("my unrelated tool", encoding="utf-8")
        self.run_install(success=False)
        self.assertEqual(self.launcher.read_text(), "my unrelated tool")
        self.assertFalse((self.prefix / "share/salvage/salvage.pyz").exists())

    def test_bundle_tampering_fails_before_install(self):
        payload = self.bundle / "salvage.pyz"
        payload.write_bytes(payload.read_bytes() + b"tampered")
        failed = self.run_install(success=False)
        self.assertIn("checksum mismatch", failed.stderr)
        self.assertFalse(self.prefix.exists())

    def test_changed_managed_file_prevents_reinstall_and_uninstall(self):
        self.run_install()
        payload = self.prefix / "share/salvage/salvage.pyz"
        payload.write_bytes(b"locally changed")
        self.run_install(success=False)
        self.run_install("--uninstall", success=False)
        self.assertEqual(payload.read_bytes(), b"locally changed")
        self.assertTrue(self.launcher.exists())

    def test_manifest_path_injection_is_rejected(self):
        self.run_install()
        manifest_path = self.prefix / "share/salvage/install-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        target = self.root / "leave me.txt"
        target.write_text("untouched", encoding="utf-8")
        manifest["files"][str(target)] = installer.digest(target.read_bytes())
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.run_install("--uninstall", success=False)
        self.assertEqual(target.read_text(), "untouched")
        self.assertTrue(self.launcher.exists())

    def test_symlink_prefix_and_managed_target_are_rejected(self):
        actual = self.root / "actual directory"
        actual.mkdir()
        try:
            self.prefix.symlink_to(actual, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable for this account")
        self.run_install(success=False)
        self.assertEqual(list(actual.iterdir()), [])
        self.prefix.unlink()
        self.run_install()
        self.launcher.unlink()
        target = self.root / "unrelated.txt"
        target.write_text("untouched", encoding="utf-8")
        self.launcher.symlink_to(target)
        self.run_install("--uninstall", success=False)
        self.assertEqual(target.read_text(), "untouched")

    def test_symlinked_payload_directory_is_rejected(self):
        self.prefix.mkdir()
        actual = self.root / "unrelated share"
        actual.mkdir()
        try:
            (self.prefix / "share").symlink_to(actual, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable for this account")
        self.run_install(success=False)
        self.assertEqual(list(actual.iterdir()), [])

    def test_directory_creation_failure_rolls_back_empty_directories(self):
        original = type(self.prefix).mkdir
        def fail_share(path, *args, **kwargs):
            if path.name == "share":
                raise OSError("simulated directory failure")
            return original(path, *args, **kwargs)
        with mock.patch.object(type(self.prefix), "mkdir", autospec=True, side_effect=fail_share):
            with self.assertRaisesRegex(OSError, "simulated directory failure"):
                installer._make_dirs(self.prefix, ["bin/salvage", "share/salvage/salvage.pyz"])
        self.assertFalse(self.prefix.exists())

    def test_transaction_rolls_back_prior_write(self):
        first = self.root / "first"
        second = self.root / "second"
        first.write_bytes(b"original")
        write = installer._atomic_write
        def fail_second(path, data, mode):
            if path == second:
                raise OSError("simulated disk failure")
            return write(path, data, mode)
        with mock.patch.object(installer, "_atomic_write", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                installer._transaction([(first, b"updated", 0o644), (second, b"new", 0o644)])
        self.assertEqual(first.read_bytes(), b"original")
        self.assertFalse(second.exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         sorted(["installer bundle", "foreign working directory", "first"]))

    def test_posix_launcher_quotes_interpreter_and_payload(self):
        if os.name == "nt":
            self.skipTest("POSIX launcher quoting")
        interpreter = self.root / "python's path ü"
        payload = self.root / "app's path ü" / "salvage.pyz"
        with mock.patch.object(installer.sys, "executable", str(interpreter)):
            launcher = installer._launcher(payload).decode("utf-8")
        command = shlex.split(launcher.splitlines()[1])
        self.assertEqual(command[:4], ["exec", str(interpreter.resolve()), "-I", str(payload)])

    def test_windows_launcher_escapes_percent_paths(self):
        with mock.patch.object(installer.os, "name", "nt"):
            # Patch Path too, since pathlib chooses its type from os.name.
            with mock.patch.object(installer, "Path", side_effect=lambda value: type(self.root)(value)):
                with mock.patch.object(installer.sys, "executable", "C:/Python %tools%/python.exe"):
                    launcher = installer._launcher(type(self.root)("C:/App %tools%/salvage.pyz"))
        self.assertIn(b"%%tools%%", launcher)
        self.assertIn(b"setlocal DisableDelayedExpansion", launcher)
        self.assertIn(b"%*", launcher)
