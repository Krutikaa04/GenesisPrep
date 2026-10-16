# Release 0.1: preparation and submission

Release work is isolated on release/0.1, incorporating reviewed master commit
709b5a7a044821f3f039aec2a693fa84574f6781 (including PR #5). Preparing tags and GitHub releases
from this branch does not merge packaging changes into master. Local/remote
master refs are checked separately before and after publication.

## Artifacts

Every artifact is built from a clean committed Git snapshot. The release name
and embedded CLI/report version must agree. Each version has:

- salvage-<version>.pyz: portable application, Python 3.10+ required.
- salvage-<version>-installer.zip: offline per-user installer and portable
  application; Python already installed, no admin privileges or dependencies.
- salvage-<version>-source.zip: complete tracked source, tests, organizer kit,
  Dockerfile and required documentation, with executable-mode metadata.
- release-manifest.json: exact commit, version, prerequisites and artifact hashes.
- SHA256SUMS: checksums for downloadable core artifacts and manifest.
- Platform validation evidence attached with the release after gates pass.

There is no bundled Python interpreter or native MSI/PKG installer. This is an
honestly labeled Python-required installer, following docs/INSTALL.md.

## Build and verification

Using the intended version's checkout and a supported Python:

```bash
python tools/build_release.py --output dist
python tools/check_release.py --dist dist --output release-validation.json
python -m unittest discover -s tests -p 'test_*.py'
python tools/compare_expected.py
python tools/evaluate.py --json evaluation.json
SALVAGE_PYTHON=python tools/docker_check.sh
```

The builder refuses dirty tracked inputs and conflicting existing output files.
Use a fresh output directory after changing the source commit or version.

Release CI builds once on Linux/Python3.12, checks repeat-build byte equality,
and tests those same downloadable bytes on Linux/Python3.10,3.12,3.14,
macOS/Python3.12 and Windows/Python3.12. The platform gate:

1. Checks checksums, committed source contents, embedded version and ten adapters.
   Runs the full test suite from extracted source without Git metadata, and
   checks that its organizer fixtures remain unchanged.
2. Runs extracted source, portable file and installed command from a foreign
   directory without checkout imports masking missing modules.
3. Requires31 identical JSON files for30 samples and all7 organizer references.
4. Verifies strict JSON keys/statuses/damage kinds/offsets and deterministic LF.
5. Exercises custom Unicode/space paths, default user paths under temporary
   homes, managed removal and unchanged source-fixture hashes.
6. Audits stdlib imports and rejects socket use through Python audit hooks.

Installer checks allow its isolated local-Python self-check process. Audit
hooks are additional evidence, not an OS network sandbox. The Docker gate builds
with --network=none and compares native output with a --network none container.
A pinned base image is preloaded during setup; recovery and install need no net.

Only publish after all relevant jobs pass. The release candidate uses
v0.1.0-rc.1; final version0.1.0 receives its own full verification before tag
v0.1.0. Published versions are treated as fixed snapshots; corrections get a
new version. Final assets are downloaded from the successful build job, so
uploaded packages are the bytes exercised by the platform jobs.

## Problem statement alignment and limits

The required ./salvage input_dir output_dir entry point, Docker build command,
JSON shapes/statuses/damage vocabulary and offline behavior remain intact.
Report-row operational notes have moved to stderr to keep only required keys.
Packaging does not alter format decoders, official fixtures, format vocabulary
or graded field layouts. The release includes the separately reviewed PR #5
VAULT/WKS verification changes. README.md and FORMAT-SPEC.md document all limits:

- Ten format families are supported within the sample-backed profiles. WPD
  unseen semantics/character tables and BRAVO formatting runs remain unproved.
- The reader caps files at128MiB. Legacy decoder ceilings/projections can
  refuse valid large files (LABLOG200000B,WKS400000B,EBCDIC500000B); VAULT work/
  output, archive entry/hash and document text/record budgets are explicit.
- Formats lacking integrity checksums can retain plausible corruption as
  structurally valid. The damage evaluation measures these cases openly.
  Passing7/7 references is compatibility evidence, not a hidden-score claim.
- Literal per-input JSON naming is impossible for reserved output aliases,
  overlong names or unavailable output storage. Failures are reported honestly;
  recovery CLI exit status stays0. Installer setup failures return nonzero.

## What to give judges

Provide the final release URL/tag and exact commit in the submission. The source
ZIP is the primary source/Docker deliverable; portable/installer downloads are
convenience routes. If extraction loses executable permissions on POSIX:

```bash
chmod +x salvage
./salvage input_dir output_dir
make build
```

Follow README.md for offline base-image prerequisites and Docker invocation.
Keep an offline copy of the source, checksums and installation instructions.
