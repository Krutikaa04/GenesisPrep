# Reference runner and saved comparison evidence

Issue #10 supplies `deadbits/validation/reference.py`. It uses the installed
engine and schema-1 evidence model, works without Git, and never modifies inputs
or downloads missing resources. Reference agreement is a whole-output comparison
for the selected answers, not arbitrary-input recovery accuracy.

From a source checkout:

```sh
python -m deadbits --verify --kit-dir samples/official --evidence-dir /tmp/reference-proof
python -m deadbits --verify --evidence-file /tmp/reference-proof/validation.json --verbose
```

From an installed or portable application, select an external local kit:

```sh
salvage --verify --kit-dir "/path/to/organizer kit" --evidence-dir "/path/to/new evidence"
python salvage-0.2.0-dev.pyz --verify --samples-dir "/path/to/input samples" --expected-dir "/path/to/answers" --evidence-dir /tmp/portable-proof
```

Installed applications do not bundle the organizer fixtures. Missing paths,
missing referenced samples, empty answer directories and malformed references
produce **unavailable**, never a passing empty comparison. Resource details and
saved summary explain the problem and the explicit kit options. A CLI run may
infer the checkout's kit only when a source layout is present; the reference
API and standalone entry point require explicit resources.

The standalone entry point accepts `--kit-dir`, `--samples-dir`,
`--expected-dir`, required `--evidence-dir`, and `--verbose`:

```sh
python -m deadbits.validation.reference --kit-dir samples/official --evidence-dir /tmp/standalone-proof
```

Both entry points return 0 for complete matching references, 1 for mismatches
or operational/persistence errors, 2 for usage errors, and 3 for unavailable
resources. Recovery's mandated zero exit behavior stays unchanged.

## API and artifacts

`run_references(output_dir=..., samples_dir=..., expected_dir=..., source_dir=None,
app_version=VERSION, commit=None)` returns `ValidationEvidence(reference=...)`.
Binding arguments with `functools.partial` supplies the schema's no-argument
Runner protocol. `run(ValidationRequest)` directly supports the #13 CLI adapter;
no changes to the recovery engine, JSON contract or model are needed.

The destination must be new or empty. The CLI prepares it before calling the
runner. Existing recovery `report.json` or previous evidence makes the directory
nonempty and is never overwritten. Destination paths equal to, inside, or above
samples, references, explicitly supplied source, or the local official kit are
refused after resolving aliases. The destination itself cannot be a symlink;
input files and references must be regular nonsymlink files. Each artifact is
created exclusively, without following/replacing an existing artifact.

A completed comparison saves:

- `actual/0001.json`, etc.: the exact decoded objects that were compared, using
  the six mandated top-level recovery keys. Numeric filenames avoid basename,
  case and Unicode normalization collisions between references.
- `expected/0001.json`, etc.: original UTF-8 answer bytes used for comparison.
- `comparison.json`: per-answer source name, artifact paths, matched result and
  structured differences (`kind`, `field`, `record_key`, `expected`, `actual`,
  `detail`). Field, missing/extra-record and damage differences are separate.
- `summary.json`: dynamic matched/total, comparisons executed, completion and
  resource problems. Unexecuted comparisons have unknown matched counts.
- `dataset-manifest.json`: sorted input/reference content hashes.
- `reference-evidence.json`: schema-1 envelope, live timestamp, application
  version, environment, dataset identity/hash and relative artifact/hash links.
  The CLI additionally saves its own `validation.json` envelope.

Unavailable runs still save summary, comparison problems and the envelope, but
no fabricated actual results or complete-dataset hash. References and referenced
samples are preflighted before any decoding. Persistence errors propagate; a
partial output directory is not a successful run and must not be reused.

The dataset's logical common root has `samples/<input basename>` and
`expected_outputs/<answer basename>`. Hash each exact input byte snapshot, sort
manifest items by `path`, serialize canonical JSON with `sort_keys=True`,
`separators=(',', ':')`, `ensure_ascii=True` and no newline, then SHA-256 those
bytes, as in schema #9. Only referenced samples are included; unreferenced files
cannot affect agreement or this dataset hash. Input hashing and decoding share
one snapshot, so changes to a file afterward cannot relabel the measured bytes.
Commit remains unknown unless explicitly supplied; no Git command is executed.
Saved evidence is historical when presented again, retaining its original context.

Safety limits: 10,000 answer files; each answer at most 8 MiB; total answer
snapshots at most 32 MiB; each sample bounded by the engine's 128 MiB read limit;
total unique sample snapshots at most 128 MiB. Limit refusals are unavailable
with explicit problems, not truncated comparisons presented as passes.

## Matching compatibility

`tools/compare_expected.py` imports the runner's `compare`/`key` compatibility
API. The one matcher preserves existing organizer-tool semantics:

- Compare format/status, requested metadata fields and all requested record
  fields. Ignore unrequested metadata/record fields.
- Match record identities using `match_on`, default `id`. Optional partial
  identities can appear without field checks. Duplicate identities use the last
  record, preserving the legacy tool's behavior rather than silently tightening
  scoring. Missing and extra identities are differences.
- Each expected damage `any_of` needs at least one actual kind. With no expected
  damage, any actual damage is a difference. As in the original tool, nonempty
  expectations allow extra damage; `lossy`, offsets and detail are not compared.

Reference loading additionally rejects unsafe input basenames, duplicate JSON
object keys, nonfinite numbers, invalid shapes/vocabulary and unusable matching
keys. It never executes reference content. This input validation does not change
matching of valid kit answers. The legacy tool's console invocation and exit
behavior remain unchanged; use the runner when saved evidence and strict input
validation are required.
