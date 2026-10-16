# Development builds and release verification

## Current baseline and published history

Issue #8 reconciles master commit 31b40d8 with the release tooling from the
immutable v0.1.0 tag (3ee8626). Development takes place on a fresh feature
branch. Do not reset or force-push the diverged release/0.1 branch to integrate
this work; use a reviewed pull request into master.

The sole application version is the VERSION literal in deadbits/version.py.
The current 0.2.0-dev value identifies unpublished development code, including
newer BRAVO and platform changes. CLI --version, report.json and built artifacts
must agree. This is not a new published release or a claim that the future demo
CLI is implemented. Published v0.1.0 remains unchanged and had 370 tests; use
unittest discovery for the current checkout's count.

## Artifacts and prerequisites

Using Python 3.10+ (Python 3.12 is the primary validation interpreter), each
clean committed snapshot can produce:

- salvage-<version>.pyz: portable recovery application.
- salvage-<version>-installer.zip: offline per-user installer and application.
- salvage-<version>-source.zip: complete tracked source, tests, organizer kit,
  Dockerfile and required documentation, with executable-mode metadata.
- release-manifest.json: exact source commit, version, prerequisites and hashes.
- SHA256SUMS: checksums for the three archives and manifest.

Python must already be installed. There is no bundled interpreter, native
MSI/PKG, administrator requirement or automatic download. See INSTALL.md.

## Build and verify a development snapshot

Commit tracked changes first; the builder intentionally refuses a dirty tree.
Use a new output directory when the commit or version changes:

```bash
python tools/build_release.py --output dist-dev
python tools/check_release.py --dist dist-dev --output out/validation-dev.json
python -m unittest discover -s tests -p 'test_*.py'
python tools/compare_expected.py
python tools/evaluate.py --json out/evaluation-dev.json
SALVAGE_PYTHON=python tools/docker_check.sh
```

The build uses canonical Git blobs, not checkout line endings or git archive
export transformations. Untracked/ignored files are not packaged. Fixed archive
metadata supports repeat-build comparison; conflicting outputs are refused.

## Automated gates

Release validation runs on pull requests into master, release branch pushes,
version tag pushes and manual dispatch. The workflow builds twice on
Linux/Python 3.12 and requires byte equality. It tests those same artifacts on
Linux/Python 3.10, 3.12 and 3.14, macOS/Python 3.12 and Windows/Python 3.12.

Each platform checks:

1. Manifest/checksum/embedded-version agreement and all ten adapters.
2. Source archive equality to committed blobs and executable launcher metadata.
3. Full tests from extracted source without Git metadata, recording the actual
   test/skip counts and verifying that organizer fixtures remain unchanged.
4. Extracted-source, portable and installed recovery from unrelated working
   directories: 31 identical JSON files for 30 samples and all seven references.
5. Strict JSON keys/statuses/damage kinds/offsets and UTF-8/LF output.
6. Unicode/space custom paths, default user paths under temporary homes and
   managed removal. The checks never install into the real user profile.
7. Standard-library imports and socket-denying Python audit hooks; only the
   exact installer local-Python self-check process is allowed.

Audit hooks are additional evidence, not an operating-system sandbox. The
separate Docker gate builds and runs with networking disabled, compares all
native/container JSON bytes, drops capabilities and uses a read-only root.
Its pinned base image must be preloaded during setup; see README.md.

## Contract, ownership and future publication

Packaging preserves the required ./salvage input_dir output_dir entry point,
zero recovery exit status, filenames and JSON vocabulary. Operational notes
use stderr rather than additional report-row keys. Installer setup failures
return nonzero. Only M3 edits the shared CLI/engine/model files; issue #9 and
other validation modules can proceed separately against agreed interfaces.

This baseline neither changes decoders nor resolves the separately tracked
BRAVO recognition tradeoff. README.md and FORMAT-SPEC.md retain exact format
assumptions, conservative resource limits, checksum limitations and filesystem
failures. Passing seven references is not a hidden-score or universal accuracy
claim. Installer distribution does not replace the required source/Docker
submission.

Do not publish from this issue. A future release needs its own approved version,
complete validation and explicitly authorized publication. Use the exact bytes
from successful CI, attach validation evidence and checksums, and treat
published tags/assets as fixed snapshots. If source ZIP extraction discards
POSIX executable permissions, run chmod +x salvage before ./salvage.
