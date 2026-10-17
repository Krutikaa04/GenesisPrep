#!/usr/bin/env python3
"""Build reproducible, stdlib-only release archives from committed Git files."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_PYTHON = "3.10"
MAIN = b'''import sys
if sys.version_info < (3, 10):
    sys.stderr.write("Salvage requires Python 3.10 or newer.\\n")
    sys.exit(0)
from deadbits.cli import main
sys.exit(main())
'''


def setup_launchers():
    """Clickable helpers use an existing interpreter; never download one."""
    result = {}
    for action, flag in (('Install', ''), ('Uninstall', '--uninstall')):
        windows = r'''@echo off
setlocal DisableDelayedExpansion
py -0p 2>nul | findstr /i /c:"python.exe" >nul
if errorlevel 1 goto missing
py -3 -I -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto missing
py -3 -I "%~dp0install.py" FLAG
set "SALVAGE_SETUP_STATUS=%ERRORLEVEL%"
goto finish
:missing
echo Python 3.10 or newer is required. Python 3.12 is recommended.
echo Install Python and its launcher from python.org, then open this file again.
echo If Python is already installed without py, run: python install.py FLAG
echo No software was downloaded or installed by this helper.
set "SALVAGE_SETUP_STATUS=1"
:finish
if not defined SALVAGE_NO_PAUSE pause
exit /b %SALVAGE_SETUP_STATUS%
'''.replace('FLAG', flag).replace('\n', '\r\n').encode('utf-8')
        mac = '''#!/bin/sh
SALVAGE_SETUP_ROOT="$(cd "$(dirname "$0")" && pwd)"
SALVAGE_SETUP_PY=""
for candidate in python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; then
    SALVAGE_SETUP_PY="$candidate"
    break
  fi
done
if [ -n "$SALVAGE_SETUP_PY" ]; then
  "$SALVAGE_SETUP_PY" -I "$SALVAGE_SETUP_ROOT/install.py" FLAG
  SALVAGE_SETUP_STATUS=$?
else
  echo 'Python 3.10 or newer is required. Python 3.12 is recommended.'
  echo 'Install Python from python.org, then open this file again.'
  echo 'No software was downloaded or installed by this helper.'
  SALVAGE_SETUP_STATUS=1
fi
if [ -t 0 ] && [ -z "$SALVAGE_NO_PAUSE" ]; then
  printf 'Press Enter to close. '
  read -r SALVAGE_SETUP_WAIT
fi
exit "$SALVAGE_SETUP_STATUS"
'''.replace('FLAG', flag).encode('utf-8')
        result[action + ' on Windows.cmd'] = (windows, 0o644)
        result[action + ' on macOS.command'] = (mac, 0o755)
    return result


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _git(repo, *args, input_data=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=input_data,
                          check=True, capture_output=True).stdout


def snapshot(repo):
    """Never include ignored/untracked caches, credentials, or a dirty file."""
    if _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("commit tracked changes before building a release")
    commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    entries = []
    # git archive applies autocrlf/export attributes. Read raw committed blobs
    # instead, so a Windows checkout and a POSIX checkout package the same bytes.
    for entry in _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not entry:
            continue
        metadata, encoded_name = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        name = encoded_name.decode("utf-8")
        if (mode not in (b"100644", b"100755") or kind != b"blob"
                or not name or name.startswith("/") or ".." in PurePosixPath(name).parts
                or "\\" in name or ":" in name):
            raise ValueError("release source must contain safe regular tracked files only: %s" % name)
        entries.append((name, mode, object_id))
    objects = _git(repo, "cat-file", "--batch",
                   input_data=b"".join(object_id + b"\n" for _, _, object_id in entries))
    files, position = {}, 0
    for name, mode, object_id in entries:
        header_end = objects.find(b"\n", position)
        if header_end < 0:
            raise ValueError("incomplete Git blob response")
        response_id, kind, length = objects[position:header_end].split()
        size = int(length)
        start, end = header_end + 1, header_end + 1 + size
        if (response_id != object_id or kind != b"blob" or size < 0
                or objects[end:end + 1] != b"\n"):
            raise ValueError("invalid Git blob response: %s" % name)
        files[name] = (objects[start:end], 0o755 if mode == b"100755" else 0o644)
        position = end + 1
    if position != len(objects):
        raise ValueError("unexpected trailing Git blob response")
    return commit, files


def _version(files):
    tree = ast.parse(files["deadbits/version.py"][0])
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise ValueError("deadbits/version.py must define one literal VERSION")
    value = versions[0]
    if not value or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for c in value):
        raise ValueError("unsafe release version")
    return value


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, (data, mode) in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    return output.getvalue()


def checksums(files):
    return "".join("%s  %s\n" % (sha256(data), name) for name, data in sorted(files.items())).encode("ascii")


def artifacts(commit, files, requested_version=None):
    version = _version(files)
    if requested_version is not None and requested_version != version:
        raise ValueError("requested version does not match committed VERSION %s" % version)
    application = {name: entry for name, entry in files.items()
                   if name.startswith("deadbits/") and name.endswith(".py")
                   and "__pycache__" not in Path(name).parts}
    if "deadbits/cli.py" not in application or "deadbits/engine.py" not in application:
        raise ValueError("committed application is incomplete")
    application["__main__.py"] = (MAIN, 0o644)
    pyz = zip_bytes(application)
    bundle = {"salvage.pyz": pyz, "install.py": files["tools/release_installer.py"][0],
              "INSTALL.md": files["docs/INSTALL.md"][0]}
    helpers = setup_launchers()
    bundle.update({name: entry[0] for name, entry in helpers.items()})
    installer = {name: (data, 0o644) for name, data in bundle.items()}
    installer.update(helpers)
    installer["SHA256SUMS"] = (checksums(bundle), 0o644)
    prefix = "salvage-%s" % version
    result = {prefix + ".pyz": pyz,
              prefix + "-installer.zip": zip_bytes(installer),
              prefix + "-source.zip": zip_bytes({prefix + "/" + name: entry for name, entry in files.items()})}
    manifest = {"version": version, "commit": commit, "minimum_python": MINIMUM_PYTHON,
                "installer_requires_python": True,
                "validation_kit": {"artifact": prefix + "-source.zip", "root": prefix,
                                   "kit_dir": "samples/official", "source_dir": "."},
                "artifacts": {name: {"sha256": sha256(data), "bytes": len(data)}
                              for name, data in sorted(result.items())}}
    result["release-manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    result["SHA256SUMS"] = checksums(result)
    return result


def build_release(output, repo=ROOT, version=None):
    commit, files = snapshot(repo)
    result = artifacts(commit, files, version)
    output = Path(output)
    if output.is_symlink():
        raise ValueError("release output must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    # Refuse unrelated files bearing our names rather than accidentally overwrite.
    for name, data in result.items():
        path = output / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != data)):
            raise ValueError("release output exists with different content: %s" % path)
    for name, data in result.items():
        (output / name).write_bytes(data)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist", help="artifact directory")
    parser.add_argument("--version", help="must match committed deadbits/version.py")
    args = parser.parse_args(argv)
    try:
        result = build_release(args.output, version=args.version)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "release build: %s\n" % exc)
    for name, data in sorted(result.items()):
        print("%s  %d bytes" % (name, len(data)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
