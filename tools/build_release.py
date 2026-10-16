#!/usr/bin/env python3
"""Build reproducible, stdlib-only release archives from committed Git files."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import tarfile
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


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def snapshot(repo):
    """Never include ignored/untracked caches, credentials, or a dirty file."""
    if _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("commit tracked changes before building a release")
    commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(_git(repo, "archive", "--format=tar", "HEAD"))) as archive:
        for item in archive:
            if item.isdir():
                continue
            if not item.isfile() or item.name.startswith("/") or ".." in Path(item.name).parts:
                raise ValueError("release source must contain regular tracked files only: %s" % item.name)
            files[item.name] = (archive.extractfile(item).read(), 0o755 if item.mode & 0o111 else 0o644)
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
    installer = {name: (data, 0o644) for name, data in bundle.items()}
    installer["SHA256SUMS"] = (checksums(bundle), 0o644)
    prefix = "salvage-%s" % version
    result = {prefix + ".pyz": pyz,
              prefix + "-installer.zip": zip_bytes(installer),
              prefix + "-source.zip": zip_bytes({prefix + "/" + name: entry for name, entry in files.items()})}
    manifest = {"version": version, "commit": commit, "minimum_python": MINIMUM_PYTHON,
                "installer_requires_python": True,
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
