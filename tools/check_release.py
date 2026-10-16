"""Verify built releases independently, without installing into the real user profile.

Run with Python 3.10+: python tools/check_release.py --dist dist --output proof.json
The check executes only locally built release code. It does not download software.
"""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent.parent
FORMATS = {"LIBRA-98", "LABLOG", "VAULT", "WKS", "WPD", "BRAVO", "CVT",
           "EBCDIC-DUMP", "WAD", "PAK", "UNKNOWN"}
STATUSES = {"ok", "partial", "unsupported", "unrecognized", "failed"}
KINDS = {"truncated", "crc_mismatch", "checksum_mismatch", "bad_length",
         "unparsed_bytes", "count_mismatch", "invalid_value", "oob_pointer",
         "index_missing", "header_checksum", "encrypted", "unknown_record"}
ADAPTERS = {"libra98", "lablog", "vault", "wks", "wpd", "bravo", "cvt",
            "ebcdic_dump", "wad", "pak"}
NETWORK_MODULES = {"socket", "urllib", "http", "ftplib", "smtplib", "imaplib",
                   "poplib", "telnetlib", "xmlrpc", "webbrowser"}
INSTALLER_SELF_CHECK = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from deadbits.version import VERSION; "
    "from deadbits.engine import ADAPTERS; import json; "
    "print(json.dumps({'version':VERSION,'adapters':sorted(m.NAME for m in ADAPTERS)}))")
OFFLINE_GUARD = """import sys
def reject_network(event, args):
    if event.startswith('socket.') or event == 'os.system':
        raise RuntimeError('release offline check blocked: ' + event)
    if event == 'subprocess.Popen':
        # POSIX reports argv; Windows reports a serialized command and can
        # report executable=None. Accept only the complete registered probe.
        allowed = globals().get('_salvage_allowed_process')
        matched = False
        if allowed is not None and args[0] in (None, allowed[0][0]):
            actual = args[1]
            if isinstance(actual, (list, tuple)):
                matched = list(actual) == allowed[0]
            elif isinstance(actual, str):
                matched = actual == allowed[1]
        if not matched:
            raise RuntimeError('release offline check blocked external process')
sys.addaudithook(reject_network)
"""


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_version(path):
    tree = ast.parse(path.read_bytes())
    values = [ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "VERSION"
                      for target in node.targets)]
    require(len(values) == 1 and isinstance(values[0], str), "expected one literal release VERSION")
    return values[0]


def json_document(data):
    def invalid(value):
        raise ValueError("non-finite JSON number: " + value)
    require(b"\r" not in data, "JSON must use LF line endings")
    return json.loads(data.decode("utf-8"), parse_constant=invalid)


def snapshot(directory):
    """Hash fixture contents without writing into their directory."""
    return {p.relative_to(directory).as_posix(): digest(p.read_bytes())
            for p in sorted(directory.rglob("*")) if p.is_file()}


def safe_zip(data):
    """Reject ambiguous, escaping or special entries before extracting a release."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    seen = set()
    for member in archive.infolist():
        # ZipInfo normalizes Windows backslashes and strips NUL suffixes.
        # Validate the actual stored name before accepting that normalization.
        name = member.orig_filename
        path = PurePosixPath(name)
        require(name and not path.is_absolute() and ".." not in path.parts
                and "\\" not in name and ":" not in name and "\0" not in name
                and name == member.filename,
                "unsafe ZIP member: " + name)
        require(name not in seen, "duplicate ZIP member: " + name)
        seen.add(name)
        kind = stat.S_IFMT(member.external_attr >> 16)
        require(kind in (0, stat.S_IFREG, stat.S_IFDIR), "special ZIP member: " + name)
    return archive


def zip_files(data):
    with safe_zip(data) as archive:
        return {entry.filename: archive.read(entry) for entry in archive.infolist()
                if not entry.is_dir()}


def verify_checksums(directory, required):
    found = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        require(match is not None, "invalid SHA256SUMS line")
        checksum, name = match.groups()
        require(name not in found and name not in (".", "..", "SHA256SUMS"),
                "duplicate or unsafe checksum entry")
        require((directory / name).is_file(), "checksummed artifact missing: " + name)
        require(digest((directory / name).read_bytes()) == checksum,
                "artifact checksum mismatch: " + name)
        found[name] = checksum
    require(set(required) <= set(found), "SHA256SUMS omits required artifacts")
    return found


def audit_python(files):
    """Check static imports; execution checks separately establish self-containment.

    This is an import audit, not an operating-system network sandbox.
    """
    imported = set()
    for name, data in files.items():
        if not name.endswith(".py"):
            continue
        tree = ast.parse(data, filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imported.add(node.module.split(".")[0])
    external = imported - set(sys.stdlib_module_names) - {"deadbits"}
    require(not external, "non-standard-library imports: " + ", ".join(sorted(external)))
    require(not imported & NETWORK_MODULES,
            "networking imports: " + ", ".join(sorted(imported & NETWORK_MODULES)))
    return sorted(imported)


def validate_outputs(directory, inputs, version):
    expected_names = {name + ".json" for name in inputs} | {"report.json"}
    files = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    require(set(files) == expected_names, "output files differ from the input contract")
    documents = {}
    for name in inputs:
        document = json_document(files[name + ".json"])
        require(isinstance(document, dict) and set(document) == {"source_file", "format", "status", "metadata",
                                   "records", "damage"}, "per-file top-level keys: " + name)
        require(document["source_file"] == name, "incorrect source_file: " + name)
        require(document["format"] in FORMATS, "invalid format: " + name)
        require(document["status"] in STATUSES, "invalid status: " + name)
        require(isinstance(document["metadata"], dict), "metadata must be an object")
        require(isinstance(document["records"], list)
                and all(isinstance(record, dict) for record in document["records"]),
                "records must contain objects")
        require(isinstance(document["damage"], list), "damage must be an array")
        for damage in document["damage"]:
            require(isinstance(damage, dict)
                    and set(damage) == {"kind", "offset", "detail", "lossy"},
                    "damage keys differ from contract")
            require(damage["kind"] in KINDS, "invalid damage kind")
            require(type(damage["offset"]) is int
                    and 0 <= damage["offset"] <= len(inputs[name]), "invalid damage offset")
            require(isinstance(damage["detail"], str)
                    and type(damage["lossy"]) is bool, "invalid damage values")
        documents[name] = document
    report = json_document(files["report.json"])
    require(isinstance(report, dict) and set(report) == {"tool_version", "files", "totals"},
            "report top-level keys")
    require(report["tool_version"] == version, "report version differs from release")
    require(isinstance(report["files"], list)
            and all(isinstance(row, dict) for row in report["files"]),
            "report files must be an array of objects")
    require([row.get("file") for row in report["files"]] == sorted(inputs),
            "report must list every input once, sorted")
    totals = {status: 0 for status in STATUSES}
    for row in report["files"]:
        require(set(row) == {"file", "format", "status", "records", "damage"},
                "report row keys differ from contract")
        document = documents[row["file"]]
        require(row["format"] == document["format"] and row["status"] == document["status"]
                and type(row["records"]) is int and row["records"] == len(document["records"])
                and type(row["damage"]) is int and row["damage"] == len(document["damage"]),
                "report row disagrees with per-file JSON")
        totals[row["status"]] += 1
    require(isinstance(report["totals"], dict) and report["totals"] == totals
            and all(type(value) is int for value in report["totals"].values()),
            "report totals disagree with per-file JSON")
    return files, documents, totals


def require_equal_outputs(reference, actual):
    require(set(reference) == set(actual), "packaged output file set differs from source")
    for name in sorted(reference):
        require(actual[name] == reference[name], "packaged JSON differs from source: " + name)


def clean_environment():
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(name, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return env


def windows_batch_command(argv, interpreter=None):
    """Give CMD its explicit outer quotes without list2cmdline escaping them.

    /s removes exactly the outer pair; inner quotes retain a batch path and
    arguments containing spaces/Unicode. Windows filenames cannot contain '"'.
    This helper receives only the checker's locally constructed command paths.
    """
    interpreter = interpreter or os.environ.get("COMSPEC", "cmd.exe")
    values = [str(interpreter), *(str(value) for value in argv)]
    require(all('"' not in value and "\n" not in value and "\r" not in value for value in values),
            "invalid quoted Windows command argument")
    inner = " ".join('"' + value + '"' for value in values[1:])
    return '"' + values[0] + '" /d /s /c "' + inner + '"'


def command(argv, cwd, env=None, input_data=None):
    arguments = [str(value) for value in argv]
    if os.name == "nt" and Path(arguments[0]).suffix.lower() in (".bat", ".cmd"):
        arguments = windows_batch_command(arguments)
    result = subprocess.run(arguments, cwd=cwd,
                            env=clean_environment() if env is None else env,
                            input=input_data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=180, check=False)
    require(result.returncode == 0,
            "release command failed (%s): %s" % (result.returncode,
             result.stderr.decode("utf-8", errors="replace")[-1000:]))
    return result


def source_command(root, args):
    # -I excludes the current directory, user site and environment import paths.
    code = OFFLINE_GUARD + ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
            "runpy.run_module('deadbits.cli',run_name='__main__')")
    return [sys.executable, "-I", "-c", code, root, *args]


def guarded_script(path, allow_installer_probe=False):
    registration = ""
    if allow_installer_probe:
        argv = [sys.executable, "-I", "-c", INSTALLER_SELF_CHECK,
                str(Path(path).resolve().parent / "salvage.pyz")]
        registration = "_salvage_allowed_process = " + repr((argv, subprocess.list2cmdline(argv))) + "\n"
    code = registration + OFFLINE_GUARD + "import runpy;runpy.run_path(sys.argv.pop(1),run_name='__main__')"
    return [sys.executable, "-I", "-c", code, path]


def check_version_help(argv, cwd, version, env=None):
    result = command([*argv, "--version"], cwd, env)
    require(re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d.])",
                      result.stdout.decode("utf-8")) is not None,
            "--version does not identify this release")
    result = command([*argv, "--help"], cwd, env)
    require("input_dir" in result.stdout.decode("utf-8")
            and "output_dir" in result.stdout.decode("utf-8"), "--help lacks CLI usage")


def committed_files(root):
    """Read canonical blobs without checkout/archive EOL conversions.

    git archive applies core.autocrlf and eol attributes. A Linux-produced
    source artifact must instead match the same Git blob bytes on Windows.
    """
    tree = command(["git", "ls-tree", "-rz", "--full-tree", "HEAD"], root).stdout
    entries = []
    for item in tree.split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        require(kind == b"blob" and mode in (b"100644", b"100755"),
                "source HEAD contains a non-regular file")
        entries.append((name.decode("utf-8"), object_id))
    object_ids = list(dict.fromkeys(object_id for _, object_id in entries))
    raw = command(["git", "cat-file", "--batch"], root,
                  input_data=b"\n".join(object_ids) + b"\n").stdout
    offset, objects = 0, {}
    for object_id in object_ids:
        end = raw.find(b"\n", offset)
        require(end >= 0, "incomplete Git blob header")
        fields = raw[offset:end].split()
        require(len(fields) == 3 and fields[0] == object_id and fields[1] == b"blob",
                "invalid Git blob header")
        size = int(fields[2])
        offset = end + 1
        require(size >= 0 and offset + size < len(raw)
                and raw[offset + size:offset + size + 1] == b"\n", "incomplete Git blob")
        objects[object_id] = raw[offset:offset + size]
        offset += size + 1
    require(offset == len(raw), "unexpected trailing Git blob data")
    return {name: objects[object_id] for name, object_id in entries}


def verify_source_snapshot(source_data, root, cwd):
    expected = committed_files(root)
    actual = zip_files(source_data)
    # The release archive can have one enclosing directory for convenient extraction.
    if "salvage" not in actual:
        prefixes = {name.split("/", 1)[0] for name in actual}
        require(len(prefixes) == 1 and all("/" in name for name in actual),
                "source ZIP has no coherent source root")
        actual = {name.split("/", 1)[1]: data for name, data in actual.items()}
    require(set(actual) == set(expected), "source ZIP differs from tracked HEAD file set")
    for name in expected:
        require(actual[name] == expected[name], "source ZIP differs from HEAD: " + name)
    required = {"salvage", "salvage.bat", "Dockerfile", "AGENTS.md",
                "samples/official/OUTPUT-CONTRACT.md", "tools/compare_expected.py"}
    require(required <= set(actual) and any(name.startswith("tests/") for name in actual),
            "source release omits required submission files")
    with safe_zip(source_data) as archive:
        launcher = next(entry for entry in archive.infolist()
                        if entry.filename == "salvage" or entry.filename.endswith("/salvage"))
        require(launcher.external_attr >> 16 & 0o111, "source salvage launcher is not executable")
        archive.extractall(cwd)
        if os.name != "nt":
            # zipfile.extractall ignores stored POSIX modes. Reproduce normal
            # unzip behavior so the source's ./salvage launcher can be tested.
            for entry in archive.infolist():
                if not entry.is_dir():
                    (cwd / entry.filename).chmod((entry.external_attr >> 16) & 0o777)
    prefix = launcher.filename[:-len("salvage")]
    return len(actual), cwd / prefix


def verify(dist, root=ROOT):
    root, dist = Path(root).resolve(), Path(dist).resolve()
    version = read_version(root / "deadbits" / "version.py")
    prefix = "salvage-" + version
    names = [prefix + ".pyz", prefix + "-installer.zip", prefix + "-source.zip"]
    checksums = verify_checksums(dist, [*names, "release-manifest.json"])
    manifest = json_document((dist / "release-manifest.json").read_bytes())
    commit = command(["git", "rev-parse", "HEAD"], root).stdout.decode("ascii").strip()
    require(manifest.get("version") == version and manifest.get("commit") == commit,
            "release manifest version/commit differs from source HEAD")
    require(manifest.get("minimum_python") == "3.10"
            and manifest.get("installer_requires_python") is True,
            "release manifest has incorrect installation prerequisites")
    require(set(manifest.get("artifacts", {})) == set(names), "manifest artifact file set differs")
    for name in names:
        require(manifest["artifacts"][name] == {"sha256": checksums[name],
                                               "bytes": (dist / name).stat().st_size},
                "manifest artifact hash/length differs: " + name)
    portable = (dist / names[0]).read_bytes()
    runtime = zip_files(portable)
    require({"deadbits/formats/" + name + ".py" for name in ADAPTERS} <= set(runtime),
            "portable release omits a format adapter")
    runtime_imports = audit_python(runtime)
    installer_files = zip_files((dist / names[1]).read_bytes())
    require(set(installer_files) == {"install.py", "salvage.pyz", "INSTALL.md", "SHA256SUMS"},
            "installer ZIP contents differ from release layout")
    require(installer_files["salvage.pyz"] == portable, "installer embeds another portable build")
    installer_imports = audit_python({"install.py": installer_files["install.py"]})
    kit = root / "samples" / "official"
    before = snapshot(kit)
    samples = {p.name: p.read_bytes() for p in sorted((kit / "samples").iterdir()) if p.is_file()}
    require(len(samples) == 30, "expected the 30 organizer samples")
    proof = {"version": version, "python": platform.python_version(),
             "system": platform.system(), "architecture": platform.machine(),
             "artifact_sha256": checksums,
             "commit": commit, "checks": [], "network_check": {
                 "method": "static import audit plus socket-denying Python audit hook; installer local-Python self-check allowed",
                 "python_audit_hook": True,
                 "os_network_sandbox": False,
                 "runtime_imports": runtime_imports, "installer_imports": installer_imports}}
    with tempfile.TemporaryDirectory(prefix="salvage-release-check-") as temp:
        # macOS temporary paths can contain a /var symlink; installer checks
        # intentionally reject symlink ancestors, so use the real directory.
        work = Path(temp).resolve()
        cwd = work / "unrelated working directory"
        cwd.mkdir()
        source_files, source_root = verify_source_snapshot((dist / names[2]).read_bytes(), root,
                                                           work / "source")
        proof["source_files"] = source_files
        proof["checks"].append("source archive equals tracked HEAD, including executable launcher")
        source_kit = source_root / "samples" / "official"
        source_before = snapshot(source_kit)
        tested = command([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                          "-p", "test_*.py"], source_root)
        test_log = tested.stdout + b"\n" + tested.stderr
        count = re.search(rb"(?:^|\n)Ran (\d+) tests? in ", test_log)
        require(count is not None and int(count.group(1)) > 0,
                "source archive unit suite did not report any tests")
        skipped = re.search(rb"(?:^|\n)OK \(skipped=(\d+)\)", test_log)
        proof["source_tests"] = int(count.group(1))
        proof["source_tests_skipped"] = int(skipped.group(1)) if skipped else 0
        require(snapshot(source_kit) == source_before,
                "source archive tests modified organizer fixtures")
        proof["checks"].append("full unit suite passes from extracted source without Git metadata")
        bundle = work / "moved bundle ü"
        bundle.mkdir()
        with safe_zip((dist / names[1]).read_bytes()) as archive:
            archive.extractall(bundle)
        verify_checksums(bundle, ["salvage.pyz", "install.py", "INSTALL.md"])
        source = source_command(source_root, [])
        portable_cmd = [sys.executable, "-I", bundle / "salvage.pyz"]
        check_version_help(source, cwd, version)
        check_version_help(portable_cmd, cwd, version)
        probe = ("import json,sys;sys.path.insert(0,sys.argv[1]);"
                 "from deadbits.engine import ADAPTERS;"
                 "print(json.dumps(sorted(a.NAME for a in ADAPTERS)))")
        discovered = json.loads(command([sys.executable, "-I", "-c", probe,
                                         bundle / "salvage.pyz"], cwd).stdout)
        require(discovered == sorted(FORMATS - {"UNKNOWN"}),
                "packaged adapter discovery does not load all ten formats")
        source_out, portable_out = work / "source outputs", work / "portable outputs"
        command([*source, kit / "samples", source_out], cwd)
        command([*guarded_script(bundle / "salvage.pyz"), kit / "samples", portable_out], cwd)
        baseline, source_docs, totals = validate_outputs(source_out, samples, version)
        output, _, _ = validate_outputs(portable_out, samples, version)
        require_equal_outputs(baseline, output)
        proof["sample_files"], proof["json_files"], proof["totals"] = len(samples), len(output), totals
        proof["checks"].append("isolated portable CLI equals source for all 31 JSON files")
        # Load the existing organizer comparator only after isolated CLI executions.
        sys.path.insert(0, str(source_root / "tools"))
        from compare_expected import compare
        references = sorted((kit / "expected_outputs").glob("*.json"))
        require(len(references) == 7, "expected seven independent organizer references")
        for reference in references:
            expected = json.loads(reference.read_text(encoding="utf-8"))
            require(not compare(source_docs[expected["file"]], expected),
                    "organizer reference mismatch: " + expected["file"])
        proof["reference_matches"] = len(references)
        proof["checks"].append("strict JSON contract and all seven organizer references")
        custom = work / "installation with spaces ü"
        install_cmd = guarded_script(bundle / "install.py", allow_installer_probe=True)
        command([*install_cmd, "--prefix", custom], cwd)
        installed = custom / "bin" / ("salvage.cmd" if os.name == "nt" else "salvage")
        require(installed.is_file(), "installer did not create the user command")
        command_argv = [installed]
        check_version_help(command_argv, cwd, version)
        installed_out = work / "installed outputs"
        command([*command_argv, kit / "samples", installed_out], cwd)
        output, _, _ = validate_outputs(installed_out, samples, version)
        require_equal_outputs(baseline, output)
        command([*install_cmd, "--prefix", custom, "--uninstall"], cwd)
        require(not installed.exists()
                and not (custom / "share" / "salvage" / "salvage.pyz").exists(),
                "uninstall left an executable or application payload")
        proof["checks"].append("custom Unicode/space prefix installation, installed CLI parity and removal")
        # Test defaults only with subprocess-local fake user directories.
        user = work / "temporary user ü"
        user.mkdir()
        env = clean_environment()
        env.update(HOME=str(user), USERPROFILE=str(user),
                   LOCALAPPDATA=str(user / "Local AppData"), APPDATA=str(user / "AppData"))
        command(install_cmd, cwd, env)
        default_payloads = list(user.rglob("salvage.pyz"))
        require(len(default_payloads) == 1, "default install did not remain in the fake user directory")
        command([*install_cmd, "--uninstall"], cwd, env)
        require(not list(user.rglob("salvage.pyz")), "default uninstall left the application payload")
        proof["checks"].append("default user installation/removal confined to temporary user profile")
    require(snapshot(kit) == before, "organizer fixtures were modified by release checks")
    proof["checks"].extend(["all ten adapters discovered from the portable archive",
                            "organizer fixtures unchanged", "version and help work outside the repository",
                            "source/portable decoding and install/removal deny socket audit events"])
    proof["passed"] = True
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True, help="directory containing built release files")
    parser.add_argument("--output", type=Path, help="save verification evidence as JSON")
    args = parser.parse_args(argv)
    try:
        proof = verify(args.dist)
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print("Release verification FAILED: " + str(exc), file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Release %s verified: %d samples, %d byte-identical JSON files, %d/7 references (%s, Python %s)" %
          (proof["version"], proof["sample_files"], proof["json_files"],
           proof["reference_matches"], proof["system"], proof["python"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
