# Benchmark evidence service

Issue #12 owns the new `deadbits/validation/benchmark.py`, its tests, and this
document. Existing `tools/evaluate.py`, mutation tools, engine, schema, and CLI
files stay with their owners. The service calls the existing evaluator directly;
it does not implement another matching or scoring algorithm.

The `run(request) -> ValidationEvidence` entry point fits the existing
`diagnostics.ValidationRequest`. The already merged CLI discovers it lazily:

```console
python -m deadbits.cli --benchmark --source-dir /path/to/source-checkout --samples-dir /path/to/samples --expected-dir /path/to/expected --evidence-dir /path/to/new-proof
python -m deadbits.cli --benchmark --source-dir /path/to/source-checkout --kit-dir /path/to/kit --corpus-dir /path/to/variants --evidence-dir /path/to/other-proof --verbose
```

`--corpus-dir` is optional. Without it, the existing six deterministic mutations
are generated in memory. With it, the evaluator validates the saved manifest,
original hashes, complete mutation set, parameters, hashes, and actual variant
bytes. All paths are local and all operations are offline. The output directory
must be new and separate from the source checkout, samples, references, and
persisted corpus. Official fixtures are read-only.

`python -m deadbits.validation.benchmark` also exposes these explicit path options;
unlike the recovery CLI, it does not infer sample/reference paths. Python callers
can use `run_benchmark(samples_dir=..., expected_dir=..., source_dir=...,
corpus_dir=None, output_dir=None, decoder=salvage_bytes, commit=None)` directly.
Its optional output directory can already exist, but none of its artifact names
may exist. Without an output directory it returns evidence without persistence.
Bind arguments with `functools.partial` for the zero-argument `Runner` protocol.

Source scoring tools are required. Portable applications do not bundle `tools/`;
an explicit trusted source kit supplies `evaluate.py` and `make_variants.py`.
These are executed as Python code, with their legacy import-path effects restored
after loading. The application decoder remains the currently running version.
Use compatible source tools; the scorer file hashes identify the actual semantics.

## Outputs and metric semantics

The integrated CLI saves `validation.json`, the schema-1 evidence envelope. The
service saves three artifacts alongside it, referenced by relative path and hash:

- `cases.json`: every mutation, including unchanged cases, its existing evaluator
  counters, mutation parameters, input hash, actual decoder output, assessment
  denominators, source baselines, and original decoder outputs.
- `summary.json`: rows grouped by **baseline and format**, with counts, explicit
  numerator/denominator/value metrics, detection coverage, unknown-format retention,
  dataset context, limitations, and original-decode crash counts/denominator.
- `dataset.json`: the sorted input/scoring manifest and its SHA-256 identity.

There is no combined accuracy percentage across organizer and regression rows.
Organizer references support independent claims only for their graded fields.
Decoder-derived pristine output establishes regression equality, not independent
accuracy. Original unverified and optional reference records remain excluded from
expected-record denominators. An explicitly empty reference directory selects
regression-only evaluation; it does not invent organizer truth. A missing requested
directory is unavailable. Unknown formats keep record counts/rates unknown in the
evidence and summary; raw case counters retain the evaluator's diagnostic zeros.

Recovery means matched expected keys (`recovered_records`), not necessarily
correct values. Complete records have every expected field present and equal.
Wrong records assert an unequal field or are unexpected under exhaustive truth;
missing fields alone are incomplete. Wrong and false-verified rates use assessed
actual outputs and assessed verified outputs, respectively. A duplicate can make
wrong counts exceed expected records; optional/unassessed outputs never dilute
these denominators. Verification uses the evaluator's existing `is_verified` rule.

The service obtains assessment denominators from `compare_records` itself:
`recovered_records + unexpected_records` counts assessed outputs. On partial
baselines, prefix differences identify which verified outputs were assessed
without reimplementing greedy key matching. Fully assessed output has a linear
fast path. Mixed partial baselines can need quadratic comparator probes; this
adapter prioritizes exact semantic reuse pending an M3-owned comparator extension.

Every summary excludes unchanged mutations from **all** rates and case counts.
The full ledger keeps them for audit. Zero denominators are unavailable. Detection
coverage is detected known formats / known-format cases; unknown-format retention
is separately unknown-stayed-unknown / unknown-format cases. Coverage is exposed
in `summary.json` because schema 1 has no coverage field. Generic CLI presentation
shows the schema measurements and links the summary artifact.

Changed-case crash counts include escaping exceptions and engine-caught decoder
exceptions, using the evaluator's `decode`. Original-decode crashes are separately
reported over source samples and mark resources unavailable: their absence must
not be mistaken for a reliable baseline. A completed crash-free benchmark can be
`measured` even when recovery is imperfect; it never promises arbitrary-file accuracy.

Missing resources, empty corpora, and groups containing only no-op mutations are
unavailable. Malformed/tampered corpora and changing inputs invalidate the run.
The service preserves diagnostic cases from an interrupted measurement but returns
unknown metrics rather than passing a partial result. CLI exit codes follow #13:
0 complete, 1 failed, 2 usage, 3 unavailable. Recovery still exits zero.

## Provenance and equivalence

Each row carries the canonical app version, Python/platform, live timestamp,
source-kit path, and content identity. Commit is collected only from a clean
application checkout with Git available; otherwise it stays unknown unless the
caller supplies it. This commit identifies the application; scorer hashes identify
the source tools separately. Custom decoder callers must supply appropriate
provenance and must not claim that the app commit identifies arbitrary callbacks.

Dataset hashing follows schema 1: canonical UTF-8 JSON (`sort_keys=True`,
`separators=(',', ':')`, `ensure_ascii=True`, no trailing newline) of a list sorted
by relative POSIX label/path, each entry `{path, sha256}`. Distinct labels cover
`samples/`, `expected/`, `scoring/`, and optional `corpus/`. Every selected top-level
regular sample, reference JSON, both scoring/mutation source files, and persisted
corpus files are included. Inputs are hashed before and after evaluation; changes
invalidate the measurement. These checks do not provide a transactional filesystem
snapshot. Saved evidence must be displayed as historical per the schema contract.

Tests compare every original case counter and per-row recovery, completeness,
coverage and crash measurement to `tools/evaluate.py` using the same decoder and
corpus. They cover both the official sample kit and a persisted synthetic corpus,
plus independent duplicate/optional/verification denominator examples. The old
mixed aggregate is deliberately not copied into the new summary.
