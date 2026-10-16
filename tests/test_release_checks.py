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
from check_release import (OFFLINE_GUARD, STATUSES, audit_python, digest, json_document,
                           read_version, require_equal_outputs, safe_zip,
                           validate_outputs, verify_checksums, verify_source_snapshot)


def zip_data(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
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
        for name in ("../escape", "/absolute", "C:/drive", "folder\\escape"):
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
        original = zip_data({"salvage": b"original"})
        changed = zip_data({"salvage-0.1/salvage": b"changed"})
        result = subprocess.CompletedProcess([], 0, stdout=original, stderr=b"")
        with tempfile.TemporaryDirectory() as temp, mock.patch("check_release.command", return_value=result):
            with self.assertRaisesRegex(ValueError, "differs from HEAD: salvage"):
                verify_source_snapshot(changed, ROOT, Path(temp))

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

    def test_version_is_read_as_data_without_executing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "version.py"
            source.write_text("VERSION = '0.1.0-rc.1'\nraise RuntimeError('must not run')\n")
            self.assertEqual(read_version(source), "0.1.0-rc.1")


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
        (self.directory / "test.dat.json").write_text(json.dumps(self.document) + "\n", encoding="utf-8")
        (self.directory / "report.json").write_text(json.dumps(self.report) + "\n", encoding="utf-8")

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
