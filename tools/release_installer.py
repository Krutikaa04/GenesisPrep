#!/usr/bin/env python3
"""Offline, per-user installer shipped as install.py beside salvage.pyz."""
import sys

if sys.version_info < (3, 10):
    sys.stderr.write("Salvage installation requires Python 3.10 or newer.\n")
    sys.exit(1)

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import zipfile

MARKER = "salvage-user-install-v1"
ADAPTER_NAMES = {"BRAVO", "CVT", "EBCDIC-DUMP", "LABLOG", "LIBRA-98",
                 "PAK", "VAULT", "WAD", "WKS", "WPD"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def default_prefix():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "Programs" / "Salvage" if base else Path.home() / "AppData" / "Local" / "Programs" / "Salvage"
    return Path.home() / ".local"


def normalized_prefix(value):
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    # Do not resolve first: that would silently accept an existing symlink.
    for component in reversed((path,) + tuple(path.parents)):
        if component.is_symlink():
            raise ValueError("refusing symlink in installation path: %s" % component)
        if component.exists() and not component.is_dir():
            raise ValueError("installation path is not a directory: %s" % component)
    return path


def _safe_file(path):
    if path.is_symlink():
        raise ValueError("refusing symlink: %s" % path)
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("not a regular file: %s" % path)


def _atomic_write(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix=".salvage-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _transaction(changes):
    """Restore managed files on ordinary write/unlink failure; never delete peers."""
    backups = {}
    applied = []
    for path, _, _ in changes:
        _safe_file(path)
        backups[path] = ((path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                         if path.exists() else None)
    try:
        for path, data, mode in changes:
            if data is None:
                path.unlink()
            else:
                _atomic_write(path, data, mode)
            applied.append(path)
    except Exception:
        for path in reversed(applied):
            old = backups[path]
            if old is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, old[0], old[1])
        raise


def _layout(prefix):
    launcher = "bin/salvage.cmd" if os.name == "nt" else "bin/salvage"
    return launcher, "share/salvage/salvage.pyz", "share/salvage/install-manifest.json"


def _existing(prefix, files, manifest_name):
    manifest_path = prefix / manifest_name
    _safe_file(manifest_path)
    if not manifest_path.exists():
        for name in files:
            _safe_file(prefix / name)
            if (prefix / name).exists():
                raise ValueError("refusing to overwrite unmanaged file: %s" % (prefix / name))
        return None
    if manifest_path.stat().st_size > 65536:
        raise ValueError("invalid installation manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("installer") != MARKER
            or not isinstance(manifest.get("files"), dict)
            or set(manifest["files"]) != set(files)):
        raise ValueError("unrecognized installation manifest")
    for name in files:
        path = prefix / name
        _safe_file(path)
        if not path.exists() or digest(path.read_bytes()) != manifest["files"][name]:
            raise ValueError("installed file changed or missing; refusing modification: %s" % path)
    return manifest


def _bundle(bundle):
    """Checksums detect accidental corruption; release SHA256SUMS covers the bundle."""
    names = ("install.py", "salvage.pyz", "INSTALL.md")
    sums_path = bundle / "SHA256SUMS"
    _safe_file(sums_path)
    expected = {}
    for line in sums_path.read_text(encoding="ascii").splitlines():
        checksum, name = line.split("  ", 1)
        if name not in names or name in expected or len(checksum) != 64:
            raise ValueError("invalid installer checksums")
        expected[name] = checksum
    if set(expected) != set(names):
        raise ValueError("incomplete installer checksums")
    data = {}
    for name in names:
        path = bundle / name
        _safe_file(path)
        data[name] = path.read_bytes()
        if digest(data[name]) != expected[name]:
            raise ValueError("installer checksum mismatch: %s" % name)
    with zipfile.ZipFile(bundle / "salvage.pyz") as archive:
        tree = ast.parse(archive.read("deadbits/version.py"))
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise ValueError("invalid application version")
    return data["salvage.pyz"], versions[0]


def _self_check(payload):
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from deadbits.version import VERSION; "
            "from deadbits.engine import ADAPTERS; import json; "
            "print(json.dumps({'version':VERSION,'adapters':sorted(m.NAME for m in ADAPTERS)}))")
    checked = subprocess.run([sys.executable, "-I", "-c", code, str(payload)],
                             capture_output=True, text=True, timeout=30, check=True)
    result = json.loads(checked.stdout)
    if set(result.get("adapters", [])) != ADAPTER_NAMES or len(result["adapters"]) != 10:
        raise ValueError("application self-check did not discover all ten adapters")
    return result["version"]


def _launcher(payload):
    interpreter = str(Path(sys.executable).resolve())
    if os.name == "nt":
        # Percent expansion applies even inside CMD double quotes.
        quote = lambda value: value.replace("%", "%%")
        return ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                'for /f "tokens=2 delims=:" %%%%A in (\'chcp\') do set "_SALVAGE_OLD_CP=%%%%A"\r\n'
                'chcp 65001 >nul\r\n'
                '"%s" -I "%s" %%*\r\n'
                'set "_SALVAGE_STATUS=%%ERRORLEVEL%%"\r\n'
                'chcp %%_SALVAGE_OLD_CP%% >nul\r\n'
                'exit /b %%_SALVAGE_STATUS%%\r\n'
                % (quote(interpreter), quote(str(payload)))).encode("utf-8")
    return ("#!/bin/sh\nexec %s -I %s \"$@\"\n"
            % (shlex.quote(interpreter), shlex.quote(str(payload)))).encode("utf-8")


def _make_dirs(prefix, names):
    created = []
    try:
        for name in names:
            parent = (prefix / name).parent
            normalized_prefix(parent)
            missing = []
            probe = parent
            while not probe.exists():
                missing.append(probe)
                probe = probe.parent
            for directory in reversed(missing):
                directory.mkdir()
                created.append(directory)
    except Exception:
        _remove_empty(created)
        raise
    return created


def _remove_empty(directories):
    for directory in reversed(directories):
        try:
            directory.rmdir()
        except OSError:
            pass


def install(prefix, bundle):
    prefix = normalized_prefix(prefix)
    launcher_name, payload_name, manifest_name = _layout(prefix)
    names = (launcher_name, payload_name)
    for name in names + (manifest_name,):
        normalized_prefix((prefix / name).parent)
    _existing(prefix, names, manifest_name)
    payload, version = _bundle(bundle)
    if _self_check(bundle / "salvage.pyz") != version:
        raise ValueError("application version self-check failed")
    contents = {launcher_name: _launcher(prefix / payload_name), payload_name: payload}
    manifest = {"installer": MARKER, "version": version,
                "python": str(Path(sys.executable).resolve()),
                "files": {name: digest(data) for name, data in contents.items()}}
    contents[manifest_name] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    created = _make_dirs(prefix, contents)
    try:
        _transaction([(prefix / name, data, 0o755 if name == launcher_name else 0o644)
                      for name, data in contents.items()])
    except Exception:
        _remove_empty(created)
        raise
    launcher = prefix / launcher_name
    print("Installed Salvage %s: %s" % (version, launcher))
    if os.name == "nt":
        print('Run directly: "%s" --help' % launcher)
        print('For this CMD session: set "PATH=%s;%%PATH%%"' % (prefix / "bin"))
    else:
        print("Run directly: %s --help" % shlex.quote(str(launcher)))
        print("For this shell session: export PATH=%s:\"$PATH\"" % shlex.quote(str(prefix / "bin")))
    print("Keep this Python installation available; it is used by the launcher.")


def uninstall(prefix):
    prefix = normalized_prefix(prefix)
    launcher_name, payload_name, manifest_name = _layout(prefix)
    names = (launcher_name, payload_name)
    for name in names + (manifest_name,):
        normalized_prefix((prefix / name).parent)
    if _existing(prefix, names, manifest_name) is None:
        print("Salvage is not installed at %s" % prefix)
        return
    _transaction([(prefix / name, None, 0) for name in names + (manifest_name,)])
    # Remove only our known directories, and only when empty.
    _remove_empty([prefix, prefix / "bin", prefix / "share", prefix / "share/salvage"])
    print("Removed Salvage from %s; unrelated files were preserved." % prefix)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install Salvage offline for the current user (Python 3.10+ required).")
    parser.add_argument("--prefix", type=Path, default=default_prefix(), help="installation prefix (default: %(default)s)")
    parser.add_argument("--uninstall", action="store_true", help="remove unchanged files managed by this installer")
    args = parser.parse_args(argv)
    try:
        if args.uninstall:
            uninstall(args.prefix)
        else:
            install(args.prefix, Path(__file__).resolve().parent)
    except Exception as exc:
        print("Salvage installer: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
