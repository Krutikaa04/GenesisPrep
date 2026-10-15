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
handoff. The final suite has **82 passing tests**, including the existing
reference, CLI and mutation suites and 63 new M1 tests.

```sh
python -m unittest discover -s tests -p "test_*.py"
python tools/compare_expected.py
```

Results: **82 tests passed; 7/7 organizer reference outputs matched**.
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

Progress was committed and pushed to `m1` after successful full-suite and 7/7
checks. Implementation commits:

- `cecd406`: LIBRA damage matrix and semantics.
- `a9c3297`: LABLOG calibration uncertainty and block recovery.
- `e4c6753`: EBCDIC descriptor and packed-field hardening.
- `0c89ec8`: final recovery regressions and compound mutations.

Master has not been merged into or pushed to. Another member must review the
M1 PR before integration. Shared automatic adapter discovery, M2 work,
M3 platform changes and the Docker release/parity check remain their owners'
work; this report does not claim they were completed.
