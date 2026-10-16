"""Independent release gates reject tampering and contract drift."""
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from check_release import (INSTALLER_SELF_CHECK, OFFLINE_GUARD, STATUSES, audit_python, digest, json_document,
                           committed_files, read_version, require_equal_outputs, safe_zip,
                           validate_outputs, verify_checksums, verify_source_snapshot,
                           windows_batch_command)


def zip_data(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            # Preserve intentionally hostile ZIP bytes even on Windows, where
            # ZipInfo.__init__ otherwise replaces backslashes with '/'.
            info.filename = info.orig_filename = name
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(info, data)
    return output.getvalue()


class ReleaseIntegrityTests(unittest.TestCase):
    def test_checksums_reject_modified_artifact_and_missing_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "salvage.pyz").write_bytes(b"original")
            (directory / "SHA256SUMS").write_text(digest(b"original") + "  salvage.pyz\n")
            self.assertEqual(verify_checksums(directory, ["salvage.pyz"]),
                             {"salvage.pyz": digest(b"original")})
            with self.assertRaisesRegex(ValueError, "omits required"):
                verify_checksums(directory, ["installer.zip"])
            (directory / "salvage.pyz").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_checksums(directory, ["salvage.pyz"])

    def test_checksum_file_rejects_escaping_or_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "artifact").write_bytes(b"x")
            line = digest(b"x") + "  artifact\n"
            for contents in (digest(b"x") + "  ../escape\n", line + line):
                (directory / "SHA256SUMS").write_text(contents)
                with self.assertRaises(ValueError):
                    verify_checksums(directory, ["artifact"])

    def test_zip_rejects_traversal_absolute_windows_and_symlink_entries(self):
        for name in ("../escape", "/absolute", "C:/drive", "folder\\escape", "file\0suffix"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe ZIP"):
                safe_zip(zip_data({name: b"x"}))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target")
        with self.assertRaisesRegex(ValueError, "special ZIP"):
            safe_zip(output.getvalue())

    def test_source_archive_must_equal_committed_content(self):
        changed = zip_data({"salvage-0.1/salvage": b"changed"})
        with tempfile.TemporaryDirectory() as temp, mock.patch("check_release.committed_files",
                                                              return_value={"salvage": b"original"}):
            with self.assertRaisesRegex(ValueError, "differs from HEAD: salvage"):
                verify_source_snapshot(changed, ROOT, Path(temp))

    def test_canonical_blobs_preserve_lf_binary_nuls_and_shared_content(self):
        text_id, binary_id = b"a" * 40, b"b" * 40
        text, binary = b"line1\nline2\n", b"\0\r\n\xff\n"
        tree = (b"100644 blob " + text_id + b"\t.dockerignore\0"
                + b"100755 blob " + text_id + b"\tsalvage\0"
                + b"100644 blob " + binary_id + b"\tsamples/official/raw.dat\0")
        batch = (text_id + b" blob " + str(len(text)).encode() + b"\n" + text + b"\n"
                 + binary_id + b" blob " + str(len(binary)).encode() + b"\n" + binary + b"\n")
        results = [subprocess.CompletedProcess([], 0, stdout=data, stderr=b"")
                   for data in (tree, batch)]
        with mock.patch("check_release.command", side_effect=results) as run:
            files = committed_files(ROOT)
        self.assertEqual(files, {".dockerignore": text, "salvage": text,
                                 "samples/official/raw.dat": binary})
        self.assertEqual(run.call_args_list[0].args[0],
                         ["git", "ls-tree", "-rz", "--full-tree", "HEAD"])
        self.assertEqual(run.call_args_list[1].kwargs["input_data"], text_id + b"\n" + binary_id + b"\n")

    @unittest.skipUnless(__import__("shutil").which("git"), "Git needed for canonical blob regression")
    def test_source_blob_comparison_ignores_autocrlf(self):
        # Override configuration only for subprocesses; never change this repository's config.
        from check_release import command as real_command
        def crlf_command(argv, cwd, env=None, input_data=None):
            if argv[0] == "git":
                argv = ["git", "-c", "core.autocrlf=true", *argv[1:]]
            return real_command(argv, cwd, env, input_data)
        with mock.patch("check_release.command", side_effect=crlf_command):
            files = committed_files(ROOT)
        canonical = subprocess.check_output(["git", "show", "HEAD:.dockerignore"], cwd=ROOT)
        self.assertEqual(files[".dockerignore"], canonical)
        self.assertNotIn(b"\r\n", files[".dockerignore"])

    def test_import_audit_rejects_network_or_third_party_modules(self):
        self.assertEqual(audit_python({"main.py": b"import json\nfrom pathlib import Path\n"}),
                         ["json", "pathlib"])
        for data, expected in ((b"import requests", "non-standard-library"),
                               (b"from urllib.request import urlopen", "networking imports")):
            with self.assertRaisesRegex(ValueError, expected):
                audit_python({"main.py": data})

    def test_offline_audit_guard_blocks_socket_before_connection(self):
        result = subprocess.run([sys.executable, "-I", "-c", OFFLINE_GUARD
                                 + "import socket;socket.socket()"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"release offline check blocked: socket.__new__", result.stderr)

    def test_offline_guard_accepts_only_registered_probe_for_windows_and_posix_events(self):
        expected = [r"C:\Python space\python.exe", "-I", "-c", INSTALLER_SELF_CHECK,
                    r"C:\bundle ü\salvage.pyz"]
        serialized = subprocess.list2cmdline(expected)
        namespace = {"_salvage_allowed_process": (expected, serialized)}
        # Test audit event handling without permanently registering a hook in
        # this test process. Real socket denial is separately tested above.
        with mock.patch.object(sys, "addaudithook"):
            exec(OFFLINE_GUARD, namespace)
        check = namespace["reject_network"]
        check("subprocess.Popen", (None, serialized, None, None))
        check("subprocess.Popen", (expected[0], expected, None, None))
        for executable, actual in (("curl.exe", serialized),
                                   (None, serialized + " unexpected"),
                                   (None, subprocess.list2cmdline([*expected[:3], "print('different')", expected[4]])),
                                   (None, subprocess.list2cmdline([*expected[:4], r"C:\other\salvage.pyz"]))):
            with self.subTest(executable=executable, actual=actual):
                with self.assertRaisesRegex(RuntimeError, "blocked external process"):
                    check("subprocess.Popen", (executable, actual, None, None))
        namespace.pop("_salvage_allowed_process")
        with self.assertRaisesRegex(RuntimeError, "blocked external process"):
            check("subprocess.Popen", (None, serialized, None, None))

    def test_version_is_read_as_data_without_executing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "version.py"
            source.write_text("VERSION = '0.1.0-rc.1'\nraise RuntimeError('must not run')\n")
            self.assertEqual(read_version(source), "0.1.0-rc.1")

    def test_windows_batch_paths_keep_inner_quotes_for_space_and_unicode_arguments(self):
        result = windows_batch_command([r"C:\User tools ü\bin\salvage.cmd",
                                        r"C:\input folder", r"C:\output folder"],
                                       interpreter=r"C:\Windows\System32\cmd.exe")
        self.assertEqual(result, '"C:\\Windows\\System32\\cmd.exe" /d /s /c '
                                 '""C:\\User tools ü\\bin\\salvage.cmd" '
                                 '"C:\\input folder" "C:\\output folder""')
        with self.assertRaisesRegex(ValueError, "invalid quoted Windows"):
            windows_batch_command(['bad"name.cmd'])


class ReleaseOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.document = {"source_file": "test.dat", "format": "LIBRA-98", "status": "ok",
                         "metadata": {}, "records": [{"id": 7}], "damage": []}
        self.row = {"file": "test.dat", "format": "LIBRA-98", "status": "ok",
                    "records": 1, "damage": 0}
        self.report = {"tool_version": "0.1.0", "files": [self.row],
                       "totals": {status: int(status == "ok") for status in STATUSES}}
        self.inputs = {"test.dat": b"source bytes"}

    def write_outputs(self):
        # Contract fixtures use exact LF bytes on every OS; text-mode writes
        # would create CRLF on Windows and mask the assertion being exercised.
        (self.directory / "test.dat.json").write_bytes((json.dumps(self.document) + "\n").encode("utf-8"))
        (self.directory / "report.json").write_bytes((json.dumps(self.report) + "\n").encode("utf-8"))

    def test_valid_contract_and_output_comparison(self):
        self.write_outputs()
        files, docs, totals = validate_outputs(self.directory, self.inputs, "0.1.0")
        self.assertEqual(docs["test.dat"], self.document)
        self.assertEqual(totals["ok"], 1)
        require_equal_outputs(files, dict(files))
        changed = dict(files, **{"test.dat.json": b"changed"})
        with self.assertRaisesRegex(ValueError, "differs from source: test.dat.json"):
            require_equal_outputs(files, changed)

    def test_extra_keys_are_rejected_at_file_and_report_row(self):
        self.document["notes"] = ["extra"]
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "per-file top-level keys"):
            validate_outputs(self.directory, self.inputs, "0.1.0")
        del self.document["notes"]
        self.row["notes"] = ["extra"]
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "report row keys"):
            validate_outputs(self.directory, self.inputs, "0.1.0")

    def test_report_counts_and_version_must_agree(self):
        self.row["records"] = 2
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "row disagrees"):
            validate_outputs(self.directory, self.inputs, "0.1.0")
        self.row["records"] = 1
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "report version"):
            validate_outputs(self.directory, self.inputs, "0.1.1")

    def test_missing_output_or_duplicate_report_input_cannot_pass(self):
        self.write_outputs()
        (self.directory / "test.dat.json").unlink()
        with self.assertRaisesRegex(ValueError, "output files differ"):
            validate_outputs(self.directory, self.inputs, "0.1.0")
        self.report["files"].append(dict(self.row))
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "every input once"):
            validate_outputs(self.directory, self.inputs, "0.1.0")

    def test_damage_bounds_and_vocabulary_are_checked(self):
        self.document["damage"] = [{"kind": "truncated", "offset": 99,
                                     "detail": "cut", "lossy": True}]
        self.row["damage"] = 1
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "damage offset"):
            validate_outputs(self.directory, self.inputs, "0.1.0")
        self.document["damage"][0].update(offset=0, kind="invented")
        self.write_outputs()
        with self.assertRaisesRegex(ValueError, "invalid damage kind"):
            validate_outputs(self.directory, self.inputs, "0.1.0")

    def test_nonfinite_numbers_and_crlf_json_are_rejected(self):
        for data in (b'{"value":NaN}', b'{"value":Infinity}', b'{}\r\n'):
            with self.assertRaises(ValueError):
                json_document(data)


if __name__ == "__main__":
    unittest.main()
