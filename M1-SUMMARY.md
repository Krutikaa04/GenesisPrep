# M1 implementation summary

Date: 2026-10-16 (Asia/Kolkata). Branch: `m1`, based on `master`.
Scope: LIBRA-98, LABLOG, and EBCDIC-DUMP only. M1 implementation is complete
within the supplied kit's evidence; integration into master requires another
team member's PR review.

| Handoff item | Result | Evidence |
|---|---|---|
| M1-1: LIBRA damage matrix | Implemented and tested | Length/checksum/count corruption; header, extended-header, record and trailer truncation; invalid offsets; garbage/zero blocks; duplicates; bytes after trailer |
| M1-2: LIBRA semantics | Implemented and documented | Deleted records retained; truncated records emit only a complete ID; extended headers respected; unknown versions unverified; flag-bit assumptions preserved |
| M1-3: LABLOG damage matrix | Implemented and tested | Header/block CRC propagation, length resync, unknown types, truncation, counts, missing/repeated/malformed tables, zero channels, non-finite coefficients, changed units |
| M1-4: LABLOG timing facts | Evidence reviewed and documented | s05 reference confirms epoch/interval; s06/s07 header/event checks are explicitly not organizer goldens |
| M1-5: EBCDIC damage matrix | Implemented and tested | RDW/BDW lengths and reserved bytes, block boundaries, trailer totals, truncation, invalid packed fields, negative B/D balances, unknown types and strict detection |

## What changed

- LIBRA recovers intact field-delimited records even when the length byte
  exceeds EOF, skips stray trailer markers in garbage, and resynchronises to
  later checksum-valid records. Duplicate IDs are retained with uncertainty.
  Partial trailers no longer cause derivative count errors. Undefined text,
  invalid ISBN/date values, and unknown versions cannot silently look verified.
- LABLOG propagates checksum/calibration uncertainty to records and events.
  Missing calibration produces null calibrated values. Broken replacement
  tables cannot leave stale calibration trusted. Changed channel units flag
  historical samples whose units the single channel list cannot represent.
  Non-finite coefficients cannot produce NaN/Infinity in JSON.
- EBCDIC isolates damaged descriptors, respects block boundaries, and recovers
  later schema-consistent records. Empty/invalid packed fields cannot crash.
  Records recovered under damaged block descriptors are unverified; credits
  reconciliation failures mark all candidate records uncertain.

## Validation

The original checkout had **19 tests**, rather than the 57 described by the
handoff. The refined suite has **119 passing tests**, including the existing
reference, CLI and mutation suites and 100 M1 tests. The first M1 pass had 82
tests; the reviewed steps 1-4 added 37 more tests.

```sh
python -m unittest discover -s tests -p "test_*.py"
python tools/compare_expected.py
```

Results: **119 tests passed; 7/7 organizer reference outputs matched**.
Tested with Python **3.12.14**. The older system Python 3.9 cannot execute the
existing CLI test fixture's `ignore_cleanup_errors` argument; no shared test
file was modified to work around that environment mismatch.

The new compound-damage tests run **1,408 deterministic cases** (seed 107105):
640 LIBRA, 384 LABLOG, and 384 EBCDIC. Each combines up to four insertions,
deletions, byte overwrites or truncations, calls the decoder directly, checks
the output contract and rejects non-finite JSON numbers. Direct random-byte
safety tests add 512 cases per decoder. These measured cases supplement the
existing every-offset truncation and byte-flip mutation suite; they do not
prove correctness for every possible input.

s20/s21 remain `ok`; s22 remains `partial` with a truncation report. The seven
reference files retain their expected statuses, records, metadata and damage
under the organizer comparison rules. No record-recovery percentage or hidden
judge score is claimed.

## Evidence limits and decisions

- LIBRA flag bits 1/2 remain assumptions, already listed in handoff question Q1.
  Duplicate-ID policy and decoding unknown versions are explicitly documented.
  Additive checksums cannot detect compensating changes; the encoding flag is
  outside individual record checksums.
- LABLOG incomplete data blocks are dropped even when some full rows remain:
  no trailing CRC is available to establish their integrity. Latest-table
  calibration is a documented assumption. s06/s07 organizer goldens are absent
  from the kit, so conditional assertions against those future references
  cannot be supplied yet. Their epoch remains independently confirmed only
  on s05.
- EBCDIC has no per-record checksum; plausible in-bounds corruption may remain
  undetected. Resynchronisation assumes the sample generator's known H/D/T
  schemas. Optional RECFM F was assessed and deliberately not guessed: no
  fixed-length fixture, LRECL or padding convention is provided. Such inputs
  remain unrecognized.

These are evidence limits, not reasons to invent missing values or layouts.
Detailed decisions and experiments are in the M1 sections of
[FORMAT-SPEC.md](FORMAT-SPEC.md) and [FIELD-LOG.md](FIELD-LOG.md).

## Parallel work and integration

Changes are confined to the three M1 decoders, their three new format-test
modules, M1 sections of shared documentation, and this requested report.
The ownership audit confirmed that other documentation sections, all shared
engine/model/CLI files, M2/M3 decoders and `samples/official/` are unchanged.
The output contract, dependencies and runtime offline behavior are unchanged.
The new accuracy benchmark is M1-owned (`tests/test_fmt_m1_accuracy.py`); shared
test helpers and M3 evaluation tooling remain untouched.

Progress was committed and pushed to `m1` after successful full-suite and 7/7
checks. Implementation commits:

- `cecd406`: LIBRA damage matrix and semantics.
- `a9c3297`: LABLOG calibration uncertainty and block recovery.
- `e4c6753`: EBCDIC descriptor and packed-field hardening.
- `0c89ec8`: first-pass recovery regressions and compound mutations.
- `1abffa4`: independent accuracy fixtures and EBCDIC recovery refinements.
- `f43e819`: CRC-proven LABLOG repairs and forward scanning.
- `b46d0da`: LIBRA header uncertainty, unique offset recovery and carried checksums.
- `ebe5822`: valid declared-chain precedence and VB type-corruption isolation.
- `8ed6040`: exact lazy interval CRCs and zero-copy candidate probing.

Master has not been merged into or pushed to. Another member must review the
M1 PR before integration. Shared automatic adapter discovery, M2 work,
M3 platform changes and the Docker release/parity check remain their owners'
work; this report does not claim they were completed.


## Reviewed improvements: steps 1-4

1. Independent fixtures choose expected fields before encoding. The 205-case
   regression corpus contains 48 LIBRA, 104 LABLOG, 48 EBCDIC and five negative
   controls. It checks dispatch, known record fields, missing/unexpected/duplicate
   records, verification, status, exact damage-kind sets, and explicitly declared
   metadata assertions. It does not use decoder output as its oracle.
2. Proven recovery/trust bugs are fixed: LIBRA code-page uncertainty and
   in-bounds offsets; EBCDIC damaged-header dispatch, block siblings and control
   text; LABLOG historical units across malformed tables. Cross-review also
   found and fixed competing LIBRA chains after trailer-only damage and all 255
   alternative first-record type bytes in a VB block.
3. LABLOG length repair requires its original stored CRC after reconstructing
   only length bytes from the known schema. Channel-count inference requires
   unique intact table/sample corroboration and a failed header CRC. No payload,
   timestamp, CRC, codec or other unreadable value is guessed.
4. Repeated scanning/hashing is bounded: LIBRA carries its checksum; LABLOG has
   monotonic lookahead and history invalidation plus exact indexed interval
   CRCs and zero-copy candidate probes. Deterministic tests count work, rather
   than relying only on machine-specific elapsed-time thresholds.

Partial-field salvage (step 5) was not implemented. Existing conservative
truncation policies, RECFM F evidence limits, and missing s06/s07 goldens remain.

## Measured before/after results

Before means decoder code at `bd30159`; after means code at `8ed6040`. Both
were run with the exact same final independent corpus on Python 3.12.14.
For the before run, a temporary archive of the old commit received only the
new evaluator file. No source fixtures or old decoder code were edited.

| Metric on this 205-case corpus | Before | After |
|---|---:|---:|
| Expected records recovered by key | 160/520 | 520/520 |
| Entire expected records correct | 144/520 | 504/520 |
| Asserted record fields correct | 1208/2864 | 2832/2864 |
| Missed expected records | 360 | 0 |
| Wrong records marked verified | 16 | 0 |
| Expected uncertainty left unmarked | 72 | 0 |
| Decoder crashes | 0 | 0 |
| Format decisions correct | 188/205 | 205/205 |
| Statuses correct | 100/205 | 205/205 |
| Damage-kind sets correct | 100/205 | 205/205 |

Record recovery by key does not imply every field is correct. The remaining
32 incorrect asserted fields are codec-dependent titles/authors in 16 records
whose header encoding flag was deliberately flipped. The original encoding
cannot be uniquely inferred from these damaged bytes. Those records remain
explicitly unverified; the benchmark includes their field errors instead of
hiding them or guessing an alternate codec. All other asserted record fields
in this corpus match their independently chosen expectations.

The 24 pristine cases with explicit metadata expectations pass all of those
assertions. Empty metadata expectations are not counted as metadata accuracy.
There are zero unexpected or duplicate records in this corpus after refinement.
These tests deliberately target known risks and are **not a hidden-judge score
estimate or a general recovery percentage**.

Reproduce the current measurements:

```sh
python tests/test_fmt_m1_accuracy.py --measure
python tests/test_fmt_m1_accuracy.py --performance
```

Performance below is the median of three decoder-only runs on this host for
800 damaged blocks/records. Times vary with hardware and process load. The
operation-count tests provide the regression guard; these timings describe
only the specified bounded patterns.

| Pattern | Input bytes | Before | After |
|---|---:|---:|---:|
| LABLOG: repeated-bad-blocks | 4,832 | 766.889 ms | 5.098 ms |
| LABLOG: dense-overlapping-markers | 6,438 | 1485.678 ms | 3.797 ms |
| LIBRA-98: malformed-record-prefixes | 28,022 | 37.725 ms | 6.799 ms |

LABLOG's next-candidate cache remains constant-size. When damaged lookahead,
repair or inference needs it, the lazy CRC prefix uses `2*(N+1)` logical bytes
plus fixed lookup tables; pristine sequential decoding avoids that allocation.
This is a deliberate linear-memory tradeoff to eliminate overlapping CRC work.
Candidate payloads are copied only after block selection; instrumentation bounds
selected payload copies by input size. Large-file platform limits and Docker
release validation remain M3's responsibility.

The updated review is [PR #2](https://github.com/Krutikaa04/GenesisPrep/pull/2).
It remains open for another member's review; master is unchanged.
