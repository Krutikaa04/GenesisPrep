# Validation evidence interface (schema 1)

Issue #9 owns the new `deadbits/validation/model.py`, this interface document,
and `tests/test_validation_model.py`. This is the validation lead's isolated
scope. No decoder, shared engine/model/CLI, official fixture, or recovery JSON
contract changes are required. The M3 integrator and runner/presenter authors
should review this contract before integrating #10–#14. This document records
the interface to review; it does not claim agreement from other contributors.

## Runner and presenter boundary

Runners construct immutable `ReferenceEvidence`, `TestEvidence`, and/or
`BenchmarkEvidence` objects, returning a `ValidationEvidence` envelope (`Runner`
protocol: `() -> ValidationEvidence`). Presenters accept that envelope and
return text (`Presenter`: `(ValidationEvidence) -> str`). A combined runner can
put reference/tests and multiple benchmark rows into one envelope. Only
requested sections are present; an omitted section is `null`, not a pass.
There is no runner execution, discovery, printing, hashing, subprocess, network,
or file access in the model. Runners own collection and artifact persistence.

Use `evidence.to_dict()` with `json.dumps(..., allow_nan=False)` to save a
separate validation artifact, never the mandated per-file JSON or report.json.
Load with `ValidationEvidence.from_dict(json.loads(...))`. Loading rejects
unsupported/missing schema versions, unknown keys, invalid counts and supplied
derived statuses/rates that disagree with counts. Derived keys can be omitted;
they are always recalculated. This is a structural check, not proof that a
saved measurement is truthful or its artifacts still exist.

## Measurements

All counts default to `None` (JSON `null` = unknown). Runners explicitly write
`0` only for measured zeroes. Negative, fractional and Boolean counts are
invalid. Every ratio saves `numerator`, `denominator`, and a derived fractional
`value`; unknown numerators/denominators or zero denominators yield `null`,
never 0% or 100%. Presenters display these as unavailable, retaining the counts.

| Measurement | Numerator | Denominator | Meaning |
| --- | --- | --- | --- |
| Reference agreement | `matched` | `total` reference comparisons | Whole-output agreement using organizer comparison semantics, not record accuracy |
| Test success | `passed` | Sum of all six outcome counts | Ordinary passing tests; skips and expected failures remain separate |
| Record recovery | `recovered_records` | `expected_records` | Expected identities recovered, whether complete or wrong |
| Completeness | `complete_records` | `expected_records` | Matched records with all expected graded fields present and equal |
| Wrong | `wrong_records` | `assessed_records` | Assessed outputs asserting unequal fields, or unexpected outputs against exhaustive truth |
| False verified | `false_verified_records` | `assessed_verified_records` | Wrong assessed outputs that claim verification |
| Crashes | `crashes` | `cases` | Cases with escaping or engine-reported decoder exceptions |

Test outcomes are mutually exclusive top-level test outcomes: `passed`,
`failed`, `errors`, `skipped`, `expected_failures`, `unexpected_successes`.
The runner must collapse multiple subtest failures/errors into the parent test
outcome (error takes precedence over failure); subtest event counts must not
inflate this denominator. `total` remains unknown until all six counts are
known. Unexpected successes fail the run. Expected failures are executed and
can yield a successful suite, but do not increase `passed`.

For benchmark rows, use one `baseline` and optional `format` per row:

- `organizer_reference`: independent organizer truth. Only these rows can
  support an independent accuracy claim for the stated dataset/fields.
- `regression_baseline`: pristine decoder-derived records; equality is regression
  agreement, not independently proven accuracy.
- `no_record_baseline`: no assessable record truth. All record counts and rates
  stay unknown; case/crash measurements can still be available.

Never combine organizer and regression rows into one accuracy percentage. The
model accepts no mixed-baseline label and provides no cross-baseline aggregation.
Aggregate counts only within the same baseline and dataset scope; divide sums,
never average percentages. Do not equate reference agreement or passing tests
with recovery accuracy. Optional partial/original unverified records are excluded
from `expected_records`. No-op mutations are excluded from all benchmark summary
counts, including `cases`; save the complete case ledger as an artifact.

`assessed_records` counts actual outputs for which correctness is assessable:
matched expected records (including incomplete records), plus unexpected records
only when the baseline is exhaustive. Optional/unassessed outputs are excluded.
`assessed_verified_records` is its subset satisfying the evaluator's
`is_verified` rule. These denominators must be collected by #12; do not derive
them from expected-record counts or fabricate them from the old ledger. Old
ledgers lacking these values keep the denominators/rates unknown, while retaining
known wrong/false-verified counts. Unexpected/duplicate outputs can make wrong
counts exceed expected-record counts. Missing fields alone are incomplete, not
wrong; unequal asserted fields are wrong. A record may be both incomplete and
wrong. Preserve existing evaluator matching/verification semantics.

## Status and missing resources

`Resource(name, available, detail)` declares required resources. A missing or
unknown required resource makes its section unavailable even if counts exist.
Runners must list missing datasets, reference directories, test discovery inputs,
or saved artifacts explicitly; the model never probes the filesystem. An empty
resource list means there are no additional declared prerequisites, not that
the model checked their existence.

- References: positive known total and all comparisons matched => `passed`;
  mismatches => `failed`; empty, unknown or missing resources => `unavailable`.
- Tests: known nonempty, non-skip-only outcomes without failures => `passed`;
  known failures/errors/unexpected successes => `failed`; unknown/empty/skip-only
  or missing resources => `unavailable`.
- Benchmarks: positive case count and known zero crashes => `measured`; known
  crashes => `failed`; missing resources/empty/unknown cases or crashes =>
  `unavailable`. Measured does not mean perfect or independently accurate.
- Envelope: any failed section => `failed`; otherwise any unavailable section,
  or no sections => `unavailable`; otherwise `complete`. It deliberately never
  says `passed`. Completion covers the supplied sections, not all possible checks.

Availability of individual metrics is independent of section status: a measured
crash benchmark can have unavailable record accuracy. Presenters must honor both
the section status and each metric's `value`, and show missing-resource reasons.

## Provenance and saved evidence

Every section has a `Context`: `app_version`, `commit`, `Dataset(identity,
sha256)`, `Environment(python_version, platform)`, `provenance` (`live`,
`historical`, `unknown`), `recorded_at`, and `source`. Defaults are unknown;
never borrow the current interpreter, version, commit or time for old evidence.
`recorded_at`, when collected, is an ISO 8601 timestamp with a timezone. The
model does not guess metadata or require Git. #8 supplies the canonical app
version; runners pass it in rather than importing a second version constant.

Dataset SHA-256 identifies the exact measured inputs and relevant truth. For
directory datasets, runners should hash UTF-8 canonical JSON (`sort_keys=True`,
`separators=(',', ':')`, `ensure_ascii=True`) of a list sorted by relative POSIX
path, each item `{"path": ..., "sha256": ...}`. Include expected references,
mutation definitions/manifest and test sources when relevant; choose a common
root with distinct paths. Hash file bytes individually first, then the manifest
JSON bytes without a trailing newline. Runners unable to establish this identity
leave it unknown. A path alone is not a content hash.

`Artifact(role, path, sha256)` links actual JSON, expected JSON, comparison details,
or a benchmark case ledger. Use paths relative to the saved evidence file's
directory for portable bundles; presenters resolve them against that directory,
never their process working directory. Hashes are SHA-256 lowercase hex or null.
Artifact paths are references, not authorization to execute files or fetch URLs.

For a live runner, explicitly mark its context live. When a presenter opens a
previously saved run, it must mark sections historical (e.g. `dataclasses.replace`
on the section/context), retaining original environment/time/version/commit and
recording the evidence path in `source`. JSON loading preserves recorded
provenance; loading a file is not a fresh measurement. Mixed live/historical
sections retain individual labels; presenters must not apply one live badge to
the whole envelope. Missing timestamps remain unknown.

```python
from deadbits.validation.model import (
    Context, Dataset, ReferenceEvidence, Resource, ValidationEvidence,
)

evidence = ValidationEvidence(reference=ReferenceEvidence(
    context=Context(provenance="live", dataset=Dataset(identity="organizer kit")),
    resources=(Resource("organizer references", available=True),),
    matched=7, total=7,
))
assert evidence.reference.agreement.value == 1.0
assert evidence.status == "complete"  # not a recovery accuracy claim
```
