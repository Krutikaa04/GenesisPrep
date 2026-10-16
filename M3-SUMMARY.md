# M3 implementation and validation report

Date: 2026-10-16. Branch: `m3`, based on integrated `master` at `9dc9754`.
Runtime implementation validated at `f876785`; this report and README record
that implementation. M1 and M2 source files and official samples were preserved.

M3 implementation is complete on its separate branch. Integration into `master`
requires another member's PR review. Server-side branch protection also requires
a repository administrator; this account has collaborator push access.

## Checklist

| Handoff item | Result |
|---|---|
| M3-0 baseline/branches | Existing M1/M2 baseline retained; new `m3` created, checked out and pushed. Admin permission unavailable for branch protection. |
| M3-1 PAK/WAD | Huge counts, duplicate names, overlapping ranges, invalid pointers, empty entries, magic variants, incomplete directories and trailing bytes handled and tested. |
| M3-2 WPD | WP5 fixed/variable framing corrected, encryption/profile variants handled, paragraphs/page breaks retained, ambiguous groups stop safely, unknown semantics explicitly unverified. |
| M3-3 BRAVO | Strict false-positive controls, empty paragraphs, missing delimiter and unsupported bytes tested. Optional formatting runs assessed and deliberately omitted because both trailers do not establish their layout. |
| M3-4 platform | Adapter discovery, executable launcher, regular-file-only bounded reads, hostile filenames, output collisions, strict JSON/result checks, atomic output and resource preflight implemented. |
| M3-5 evaluation | Deterministic corpus/evaluator, independent-reference versus regression scoring, 15 evaluator tests and full measured ledger delivered. |
| M3-6 release | Offline Docker check, CI, build/run instructions, consistent M3 format/log documentation and THIRD_PARTY.txt delivered and verified. |
| M3-7 integration | M1 PR#2 and M2 PR#3 already merged in baseline. Full baseline checks pass; baseline and M3 Docker parity verified. M3 awaits reviewed merge. |

## Resulting behavior

The shared engine automatically loads public adapter modules and isolates
broken imports, scores and decoder outputs. Ten contract-approved formats use
one CLI/report flow. Extension needs a new adapter and tests; a new output
format name still requires the integrator's deliberate vocabulary update.

PAK/WAD preserve independent entries when a sibling is damaged. Duplicate names
and overlapping data are kept with uncertainty. Hashing uses memoryviews,
exact-span caching and a bounded work budget; missing/invalid hashes are omitted.

WPD checks mirrored function sizes/subgroups/gates before moving past payload.
Broken framing cannot leak payload text into verified paragraphs. Unimplemented
function semantics are marked unknown; the sample-proven C3/C4 formatting gates
remain supported. Product/type/version support is explicitly limited to the
kit-backed profile, including its unusual version 2.0/WP5-style combination.

BRAVO keeps CR-delimited empty paragraphs but requires stronger independent
binary-trailer evidence for automatic recognition. Unsupported bytes are
flagged during independently identified salvage. No formatting-run values were
invented from the two unproved trailers.

The CLI handles per-file failures independently, preserves UTF-8/LF output and
escapes undecodable filename bytes. It refuses symlinks/FIFOs, protects sources
from same-directory writes, atomically replaces output symlinks, and reports
filesystem naming/write conflicts honestly. `report.json` retains exactly its
three top-level keys. Status names, damage kinds and six per-file keys remain
unchanged; existing optional report-row notes carry operational explanations.

## Validation evidence

- **327 tests run** locally with Python 3.12: 326 passed and one end-to-end invalid-byte-name
  fixture skipped because the host filesystem rejects creating it. Serialization
  roundtrip is still tested. Linux CI passed all 327 tests without skips.
- **7/7 organizer reference outputs match.** Existing mutation tests retain
  every-offset truncation, byte corruption, zero blocks and compound cases.
- **31 JSON files byte-identical** between native and Docker for all 30 samples,
  including the combined report. Both runs: 18 ok, 6 partial, 5 unrecognized,
  1 failed. Container runtime used `--network none`, read-only root, dropped
  capabilities, no-new-privileges and an unprivileged user. Docker build RUN
  steps used `--network=none`; the pinned base was preloaded separately.
- The same native/Docker parity check passed on integrated master 9dc9754 using
  an isolated archived snapshot. No master checkout or shared branch was edited.
- [Linux CI validation](https://github.com/Krutikaa04/GenesisPrep/actions/runs/38855908310)
  passed tests, references, evaluation and offline-container comparison. The
  committed workflow repeats these checks on future m3/master pushes and PRs.
- Independent review probed output aliasing, dense documents, small compressed
  expansion, malformed adapters and expensive preflight detection. Findings
  were fixed and covered by regression tests. Official samples have no diff.

## Measured damage evaluation

[Full reproducible ledger](reports/m3-evaluation.json): 30 samples, 180 variants,
173 changed cases, 7 no-ops excluded. Six transformations per sample: 10/50/90%
retained, one byte short, midpoint XOR 255, centered zero block up to 32 bytes.

| Evidence source | Changed cases | Recovered keys | Complete records | False verified | Crashes |
|---|---:|---:|---:|---:|---:|
| Seven organizer references | 42 | 251/366 (68.6%) | 227/366 (62.0%) | 5 | 0 |
| Pristine decoder regression baseline | 107 | 488/789 (61.9%) | 458/789 (58.0%) | 5 | 0 |
| Unknown originals | 24 | n/a | n/a | 0 | 0 |

Unknown originals stayed UNKNOWN in all 24 changed cases. Independent-reference
format recognition was 42/42; regression recognition 88/107. Missing bytes and
conservative detection reduce recovery. All per-format counts are in README
and the ledger. Unverified original/optional partial records do not inflate
denominators; duplicate keys and wrong verified values are counted explicitly.

The five reference false-verified cases are in CVT/VAULT/WKS; five regression
cases include EBCDIC/VAULT and archive payload hashes. These formats lack a full
integrity checksum, so plausible corruption can remain structurally valid.
Regression agreement is not independent accuracy evidence, and these variants
do not predict hidden judging. No universal corruption-detection claim is made.

## Explicit limits and handoff

- Global input read limit: 128MiB. Legacy decode ceiling: 2MiB, with conservative
  100,000-item projections further limiting LABLOG/WKS/EBCDIC to
  200,000/400,000/500,000 bytes. VAULT projected work/output each cap 16MiB.
  These safety policies may refuse legitimate files and report that refusal.
- PAK/WAD: 100,000 entries, unique hash work <=4x input bytes. WPD/BRAVO: 8MiB
  text and 100,000 records. Budget losses are explicit; UNKNOWN metadata scans
  only the first 1MiB. Oversized legacy detection sees at most 64KiB.
- Without BRAVO trailer proof, damaged/missing-marker files remain UNKNOWN.
  WPD character tables, unseen function semantics and BRAVO formatting runs
  remain explicitly unimplemented. M1/M2 assumptions remain documented.
- Exact output naming is impossible for some filesystem limits/collisions
  (a maximum-length basename plus `.json`, aliases, or basename `report`).
  Those files are marked failed in the combined report while siblings proceed.
  An unwritable output root can only be reported to stderr; CLI still exits 0.
- Optional report-row notes predate M3. Organizer question Q2 about extra keys
  remains open; all required fields and top-level output shapes are preserved.
- Repository owner action: enable master protection requiring reviewed PRs.
  Merge m3 only after another member reviews; keep checks green. No direct
  master push or self-approved merge was performed.

Reproduce:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python tools/compare_expected.py
python tools/evaluate.py --json /tmp/m3-evaluation.json
SALVAGE_PYTHON=python tools/docker_check.sh
```

The host Docker check used an isolated Colima profile named `genesis-m3`,
without changing the default Docker context. Its VM is stopped after validation;
Docker/Colima developer tooling and the cached base remain available to resume.
