# DeadBits — PS 02 Salvage

Offline recovery of damaged legacy binary files. One shared engine identifies
formats from bytes, runs independent adapters, and writes recovered records
with explicit uncertainty and damage evidence. Runtime and tests use Python's
standard library only; no network or AI/LLM calls.

## Release installation

The build tools package this same engine as a portable Python application
and a per-user installer ZIP. Both require an existing Python 3.10+ interpreter;
Python 3.12 is the primary tested version. There is no bundled third-party
bootloader, GUI, automatic download, or administrator requirement.

See [installation and removal](docs/INSTALL.md) for macOS, Linux and Windows.
The installer adds an interpreter-bound command under the chosen prefix and
prints PATH setup instructions without editing shell profiles or the registry.
Use `salvage --help` and `salvage --version` after installation. Source/Docker
remain the problem statement's primary submission routes.

Version, manifest, artifact hashes and exact tested commit are linked by the
release downloads. The preparation and validation process, support boundaries
and submission instructions are in [release guidance](docs/RELEASE.md).

The current source is an unpublished development baseline. Its version comes
from `deadbits/version.py`; run `./salvage --version` to inspect it. Published
`v0.1.0` remains a fixed snapshot and does not include later master changes.

## Run

Use Python 3.10 or later (validated with 3.12):

```bash
./salvage <input_dir> <output_dir>
# Equivalent native entry point:
python -m deadbits.cli <input_dir> <output_dir>
# Windows:
salvage.bat <input_dir> <output_dir>
```

Input listing is nonrecursive; directories are skipped. Output contains
`<full input basename>.json` for each processable input plus `report.json`.
The CLI exits 0 even for damaged inputs or operational errors; inspect each
status, damage entry, the combined report and stderr. Report rows contain only
the required file/format/status/records/damage keys; operational explanations
are sent to stderr. Use different input and
output directories to protect source files.

Formats: LIBRA-98, LABLOG, VAULT, WKS, EBCDIC-DUMP, CVT (SEQ/VLIR), PAK, WAD,
the kit's WordPerfect document profile, and BRAVO. Unknown structures remain
`UNKNOWN` / `unrecognized`; encrypted WPD documents are `unsupported`.

## Terminal diagnostics and evidence

`./salvage --doctor` checks the interpreter, application version, all ten adapters
and local validation resources without installing or downloading anything.
`./salvage input output --verbose` adds a per-file recovery table while keeping
mandated JSON unchanged. Recovery counts do not imply accuracy.

`--verify` now runs organizer comparisons and saves actual decoded JSON,
reference snapshots, detailed differences and a provenance envelope. Supply
`--kit-dir` for external fixtures and a new `--evidence-dir` outside protected
inputs; see [reference runner](docs/REFERENCE-RUNNER.md).

`--test --source-dir "/path/to/source kit" --evidence-dir /tmp/test-proof`
executes the selected trusted kit's `tests/` suite and saves dynamic outcomes
and detailed logs. `--benchmark` measures mutations using explicit baseline
labels and compatible scoring tools from `--source-dir`. See the
[test service](docs/UNITTEST-RUNNER.md) and [benchmark service](docs/BENCHMARK-RUNNER.md).
All three services are connected to the CLI. Missing validation resources return
unavailable (exit 3); installed applications need an external kit for tests and
benchmark scoring. All validation modes can present saved schema-1 evidence
using `--evidence-file`, labelled historical.
Validation exits are distinct from recovery's always-zero behavior. See
[CLI modes and runner integration](docs/CLI-MODES.md) for paths, examples,
exit codes and evidence protection.

Run the mentor walkthrough with
`./salvage --demo --kit-dir /path/to/kit --source-dir /path/to/source --output-dir /tmp/demo-proof`.
The same flag works in the portable/installed app; `--demo --help` lists guided,
historical-evidence and skip options. See the [mentor demo](docs/MENTOR-DEMO.md).

## Docker build and isolated run

Preload the pinned base image on a connected machine (or transfer its saved
image into an offline Docker installation):

```bash
docker pull python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
make build
# Dockerfile RUN steps have networking disabled; no packages are installed.
docker run --rm --network none -v "$PWD/in:/in:ro" -v "$PWD/out:/out" deadbits /in /out
```

Docker must already be running. `make docker-check PY=python3` builds with
networking disabled, runs the container with `--network none`, a read-only root
and dropped capabilities, and compares every output byte with a native run.
It also checks the full output filename list. M3 validation produced **31
byte-identical JSON files** for all 30 samples on native and isolated Docker
runs, both locally and in [Linux CI](https://github.com/Krutikaa04/GenesisPrep/actions/runs/38855908310).
No Docker dependency is needed for native operation.

## Validate and measure

```bash
make test PY=python3
make reference PY=python3
make evaluate PY=python3
# Optional persisted corpus; official samples remain unchanged:
python3 tools/make_variants.py /tmp/deadbits-variants
python3 tools/evaluate.py --variants /tmp/deadbits-variants --json /tmp/evaluation.json
```

The suite is discovered dynamically by `make test`; its final `Ran ... tests`
line reports the count for the executing checkout. Published v0.1.0 had 370
tests; later decoder and platform tests can change that count. Release CI tests
Windows/macOS with Python 3.12 and Linux with Python 3.10/3.12/3.14, including
pull requests into master. Platform-specific fixtures may skip where their
filesystem feature is unavailable. The suite covers reference fixtures, every-offset
truncation, byte flips,
compound damage, direct decoder safety, resource limits, filesystem failures,
adapter discovery and evaluator accounting. Organizer comparison must remain
**7/7**. The release checker independently compares source, portable and
installed output on all 30 samples, verifies all ten adapters and tests offline
installation/removal from outside the source folder. GitHub CI repeats tests, reference comparison, evaluation and native /
offline-container parity for `m3`, `master`, and pull requests into `master`.

The measured [M3 evaluation ledger](reports/m3-evaluation.json) contains all
30 sources and 180 variants: retain 10/50/90%, one byte short, midpoint byte
corruption, and a centered zero block. Its 173 changed cases exclude seven
no-ops from rates. There were **zero crashes**. Recovery counts matched record
keys; complete records require every expected graded field to agree.

Organizer references provide independent truth for seven sources:

| Format | Changed cases | Recovered keys | Complete records | False verified | Crashes |
|---|---:|---:|---:|---:|---:|
| LIBRA-98 | 12 | 46/60 | 37/60 | 0 | 0 |
| LABLOG | 6 | 87/132 | 81/132 | 0 | 0 |
| VAULT | 6 | 9/18 | 7/18 | 0 | 0 |
| WKS | 6 | 84/120 | 82/120 | 0 | 0 |
| CVT | 6 | 5/6 | 1/6 | 1 | 0 |
| EBCDIC-DUMP | 6 | 20/30 | 19/30 | 0 | 0 |
| **Total** | **42** | **251/366 (68.6%)** | **227/366 (62.0%)** | **1** | **0** |

Remaining recognized sources use verified pristine decoder output as a
**regression baseline**, which does not independently prove accuracy:

| Format | Changed cases | Recovered keys | Complete records | False verified | Crashes |
|---|---:|---:|---:|---:|---:|
| LIBRA-98 | 18 | 53/72 | 44/72 | 0 | 0 |
| LABLOG | 12 | 183/282 | 181/282 | 0 | 0 |
| VAULT | 12 | 17/36 | 11/36 | 0 | 0 |
| WKS | 12 | 108/162 | 108/162 | 0 | 0 |
| CVT | 5 | 12/15 | 10/15 | 0 | 0 |
| EBCDIC-DUMP | 12 | 32/48 | 30/48 | 1 | 0 |
| PAK | 6 | 13/24 | 13/24 | 1 | 0 |
| WAD | 6 | 24/42 | 22/42 | 2 | 0 |
| WPD | 12 | 36/48 | 29/48 | 0 | 0 |
| BRAVO | 12 | 27/60 | 21/60 | 0 | 0 |
| **Total** | **107** | **505/789 (64.0%)** | **469/789 (59.4%)** | **4** | **0** |

Issue #15 deliberately removes BRAVO's text-only identification guess. On the
same mutation corpus, BRAVO recovery falls from 41/60 to 27/60 keys and complete
records from 34/60 to 21/60; all four damaged-text cases with marker/trailer
evidence still recover. Separately, 32 independently constructed ordinary-text
controls improve from 20 false BRAVO identifications to zero (all UNKNOWN).
Reproduce the [current negative-control ledger](reports/bravo-identification.json)
with `python3 tools/evaluate_bravo.py --json /tmp/bravo-identification.json`.
These controls measure the specific ambiguity; they do not prove a general
false-identification rate or the accuracy of decoder-derived recovery baselines.

Unknown originals stayed UNKNOWN in all 24 changed cases. Zero-record
baselines have no recovery percentage. Original unverified records and optional
partial reference records are excluded from recovery denominators. Truncation
removes real bytes; these rates measure what survives this corpus, without
predicting hidden-judge results. False verified cases in unchecksummed formats
remain visible in the ledger: archive payload hashes (no stored hash to check), a flipped PETSCII or EBCDIC
character that is itself a valid character, and similar undetectable corruption. VAULT text that is not valid
UTF-8 and WKS formulas or labels failing structure checks are now flagged unverified.

## Extension and parallel ownership

Copy `deadbits/formats/_template.py` to a public module with `NAME`,
`detect(data)` and `decode(data, source_file)`. The engine discovers it without
a shared registry edit. Keep private helpers prefixed `_`, require structural
recognition evidence, bound all file-controlled work, and test damaged inputs.
Adding a new format name still requires the integrator to extend the output
contract's vocabulary deliberately.

M1 owns LIBRA/LABLOG/EBCDIC; M2 owns VAULT/WKS/CVT; M3 owns archives, documents,
platform and integration. Follow [AGENTS.md](AGENTS.md) and the full
[project handoff](PROJECT-HANDOFF.txt), work on separate branches, and merge
through a reviewed PR. Output contract keys, statuses and damage kinds remain
unchanged. Layout facts and assumptions live in [FORMAT-SPEC.md](FORMAT-SPEC.md),
experiments in [FIELD-LOG.md](FIELD-LOG.md).

## Recovery and safety limits

- Checksums can establish some integrity in LIBRA/LABLOG, with documented
  collision/header limitations. Other formats have no full integrity checksum:
  plausible in-bounds changes can remain undetected. `verified` there means
  structural consistency. A computed SHA-256 describes selected bytes.
- The file reader caps input at 128MiB and rejects symlinks/special files.
  Legacy decoders have a conservative 2MiB ceiling; structural projections
  further cap LABLOG/WKS/EBCDIC at 200,000/400,000/500,000 bytes. VAULT projected
  work/output each cap at 16MiB. These policies can refuse a legitimate file;
  refusals are explicit `failed` / `bad_length` results. Unknown-file metadata
  analyzes at most the first 1MiB and says when it is sampled.
- PAK/WAD recover at most 100,000 entries, with hash work at most four times
  input size. WPD/BRAVO cap text at 8MiB and records at 100,000. Excluded data
  is reported as loss; omitted hashes/text are never fabricated.
- BRAVO has no magic: recognition requires marker/trailer evidence. Fragments
  without that evidence remain UNKNOWN. Explicit library recovery marks all
  paragraphs unverified when identification fails. Trailer length and optional
  formatting runs remain unproved: a cut leaving enough trailer evidence or
  unrelated text with a matching binary suffix can still pass. WPD support follows the kit's header
  profile; unimplemented function semantics are flagged rather than guessed.
- Filesystem limits can make the required output impossible: names too long
  after adding `.json`, names aliasing another output, or basename `report`
  (including aliases of `report.json`) are explicitly failed in the combined
  report. An unwritable output directory is reported to stderr, with exit 0.
  Undecodable POSIX filename bytes are escaped losslessly in UTF-8 JSON.

No third-party implementation is bundled; development-time WP5 sources and
license context are recorded in [THIRD_PARTY.txt](THIRD_PARTY.txt). M3 completion
and release evidence are recorded in [M3-SUMMARY.md](M3-SUMMARY.md).
