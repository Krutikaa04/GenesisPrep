# FIELD-LOG

Dated log of what was tried, including the hypotheses that failed. Every layout in FORMAT-SPEC.md was
derived from `samples/official/`. Dates are the working-session dates.

## 2026-10-16

### LIBRA-98 (s01-s04)
* H1 `created` is a u32 unix time. **Failed**: `0x5A8B2543` = 2018, expected `1998-10-03T11:20:22`.
* H2 `created` = two DOS words, date first. **Confirmed** on s01 expected (date `0x2543`, time `0x5A8B`).
* H3 `A5 2B 00` = marker + u16 length. **Failed**: `00` is a flags byte, length is u8 (record 2: `3E 01`
  = len 62, flags 1 = checked_out, matches expected `checked_out:true`).
* H4 `year` stored directly. **Failed** (`0x018D` = 397); +1500 gives 1897. Confirmed on s01/s04.
* H5 record checksum: tried sum8/xor8/neg over several spans; `sum8(flags..before chk)` matched 22/22;
  trailer: `sum16` of everything before `END!` matched 3/3 (CRC variants did not).
* H6 `data_offset` is always 16. **Failed**: s03 has 40 (vendor string `LIBSYS/98 REL 2.1`).
* H7 text is always cp437. **Failed**: s03 bytes `0x92`, `0xDF` only make sense as cp1252; header flag
  bit0 = 1. s02 uses cp437 (`0x82` = é).
* Open: flag bits 1-2 meaning (deleted / reference_only) cannot be confirmed from the 2 reference files.


* M1-1/2 (2026-10-16): added the LIBRA damage matrix and semantics tests.
  Oversized record lengths originally bypassed field recovery and swallowed
  later intact records; recovery now precedes the EOF decision. Partial trailer
  checksums also used to allow a spurious count mismatch; now suppressed.
* Duplicate IDs are preserved and flagged, not silently collapsed. Unknown
  versions are attempted conservatively and flagged on every recovered record.
* Invalid ISBN bytes and undefined text bytes now produce `invalid_value`.
  Failed test hypothesis: a low DOS-date byte of `0xFF` is always invalid; it
  actually encodes July 31. The invalid-date mutation uses day zero instead.
* Final review: a stray `END!` inside inserted garbage could stop recovery before
  later good records; resynchronisation now distinguishes this from a real
  checksum-valid trailer. Added bad-length resynchronisation and undefined-text
  recovery tests, plus 640 seeded compound-damage direct decoder cases.
* Validation: 36 tests passed with Python 3.12.14; reference comparison 7/7.
  System Python 3.9 cannot run the existing CLI fixture's
  `TemporaryDirectory(ignore_cleanup_errors=True)`; no M3 file was changed.


* Review/refinement pass (2026-10-16): flipping the s03 header codec flag changed
  Alice's/Schloss text while record checksums passed. Codec-dependent fields
  now carry uncertainty when the trailer cannot establish header integrity;
  no alternate codec is guessed. ASCII-only records retain independent trust.
* In-bounds bad offsets skipped checksum-valid prefix records. Repair now needs
  a unique earlier full chain plus the stored checksum after only pointer repair.
  A genuine fixture with two overlapping valid chains (offsets 16 and 271,
  equal pointer byte sums) confirms that ambiguous candidates are rejected.
* Repeated prefix sums made resynchronization quadratic. Carrying checksum state
  makes measured checksum work linear with constant extra checksum memory.
  Added deterministic byte-work guards and independent vendor/compound-damage
  negative controls. A stray final END! gap now reaches the validated trailer.
* Cross-review found a stronger additive-collision case: valid chains at 16/270
  and a trailer-only +1 error could select the wrong earlier chain. Offset repair
  now refuses to override an intact declared chain, even when one alternative
  restores the checksum. The genuine nested-chain regression preserves both
  declared records and reports only the actual trailer mismatch.

### LABLOG (s05-s07)
* H1 `start` is unix time. **Failed**: gives 1972-10-11T05:07:43Z - right month/day/time, year 20 too low.
* H2 epoch 1990-01-01. **Confirmed**: `1992-10-11T05:07:43Z` (s05 expected).
* H3 interval = 50 ms literal. **Failed**: expected 500; field is in units of 10 ms.
* H4 channel table entry = unit[6]+f32+f32 (14 B). **Failed** (decoder error / wrong sizes): block length 24
  for 2 channels => 12 B per channel, unit is 4 bytes.
* H5 block CRC: tested sum/xor/CRC16 variants over several spans; CRC-16/CCITT-FALSE over `type..payload`
  matched 7/7; header CRC over bytes 0..29 matched.
* H6 only raw -32768 is a dropout. Confirmed by expected `-10091.5` (raw -20224 is a real value).


* M1-3/4 (2026-10-16): added LABLOG block/header CRC, corrupt-length
  resynchronisation, unknown-type, truncation, count, calibration replacement,
  missing/zero-channel, malformed event/sample and non-finite float tests.
* Failed policy: emitting raw values without calibration violates the meaning
  of `values[]`; now unavailable calibrated values are null and unverified.
  Failed replacement tables used to leave an older calibration trusted; now
  cleared. Skipped framing also taints later calibration until a good table.
* Truncated data blocks remain dropped: complete rows alone cannot establish
  integrity when the block CRC is absent. This is an explicit conservative choice.
* s06/s07 tests read header/event facts and confirm dropout / damaged-block
  handling. They do not claim independent confirmation of the inferred epoch.
  s06/s07 organizer goldens are not present in the supplied kit.
* Final review: a new table with changed units makes historical samples
  ambiguous under the contract's one channel list; those samples are now
  unverified. Added the regression plus 384 seeded compound-damage cases.
* Validation: 54 tests passed with Python 3.12.14; reference comparison 7/7.


* Review/refinement pass (2026-10-16): six corrupt length values on s05 dropped
  4/22 samples even though reconstructing only the length made the stored CRC
  verify. Table/sample/event lengths now use this narrowly validated repair.
  Tests reject changed CRC/payload, incomplete payload, and ambiguous evidence.
* A damaged header channel count can be independently corroborated by intact
  table and sample widths. Unique support restores data without concealing the
  failed header CRC; zero-channel headers with a valid CRC remain rejected.
* Valid -> malformed -> changed-unit tables lost historical unit provenance.
  The last known unit list is retained separately from calibration validity.
  Repeated table changes now invalidate each historical sample at most once.
* The former CRC lookahead repeatedly scanned the suffix for every bad block.
  A constant-size next-candidate/EOF cache removes that repeated scan. Added
  independent fixtures, engine-level negatives, repair rejection controls, and
  deterministic CRC-work and historical-invalidation operation guards.


* Cross-review found that a forward marker cursor alone did not bound CRC work:
  dense overlapping payload candidates still took almost six seconds at 13KB.
  Added a lazy exact interval-CRC index, independently checked against bitwise
  CRC for random/empty/max-length intervals and all 65,536 initial states.
  Deterministic operation guards count prefix bytes, range-shift steps and
  ordinary CRC bytes for dense markers and overlapping repair attempts.
* Main probes could also copy overlapping invalid payloads before selection.
  They now use memoryviews; instrumentation bounds selected payload copies by
  input size. Pristine sequential logs do not allocate the interval index.

### VAULT (s08-s10)
* H1 whole file XORed with a constant key. **Failed** (no key reveals text).
* H2 logo.bin payload stored raw. **Confirmed**: its SHA-256 matches a 20-byte window of s08 at 205.
* H3 XOR key advances with position: `(key + i) & 0xFF`. **Confirmed** on names and text payloads
  (the 40 `-` characters become a counting byte sequence).
* H4 names are length-prefixed with a plain length byte. **Partly failed**: s09 (header flags=1) XORs the
  length byte with the key too.
* H5 RLE variants (count/byte pairs, PackBits, escape byte): the 0x90 escape with BinHex semantics
  reproduces the index `size` on every compressed entry; other variants did not.
* H6 entry `flags` bit0 = RLE, bit1 = XOR (s08: report.txt 3, notes.txt 2, logo.bin 0 vs expected
  compressed true/false/false). Confirmed.

* M2 sweep (truncate at every offset, 4 byte values at every offset of s08-s10): no crash, contract valid. Found:
  records decoded with a wrong `xor_key` stayed `verified` (length-correct garbage) -> added printable-name and
  no-control-character text checks. A key off by one (0x21 vs 0x22) still gives printable text: **cannot be detected**,
  documented as a limit.
* H7 recover the key by choosing the one that makes all names/XOR text most printable. **Rejected**: `printable_score`
  ties between neighbouring keys on short lowercase names, and recovering would be a guess.
* H8 scan for `BL`+id blocks when the index is lost. **Rejected**: type, flags, names and the size check all live in
  the index; a record without them cannot be graded or verified.
* `sha256` of a payload whose length != `size` is dropped: it cannot match the original and only looks authoritative.
* Entry flag bit0 flipped on a block with no 0x90 byte produces an identical payload (only `compressed` differs): undetectable.

### WKS (s11-s13)
* Record stream per the public Lotus layout validated on s11 expected. s12 is a stress file: out-of-order
  cells, a cell written twice (kept last), blank formatted cell, unknown opcode 0xFA, named range.
* H number_format must be emitted for every non-default format. **Rejected**: s11 expected has none for
  fmt 0x22 cells, so only date/time formats are emitted.

* M2 sweep: flipping the high length byte of a skipped settings record (s12 offset 26 -> length 257) made the decoder
  jump 257 bytes, land by luck on a real record boundary and report `ok` with 7 of 9 cells gone (s11 offset 30: 12 of 20).
  Fix: known opcodes use their known length when a strict record chain follows it; unknown/odd cases resync (see FORMAT-SPEC).
* H a record chain of 2 records is enough to resync. **Rejected**: random payload bytes can look like two records;
  3 records (or a chain ending in EOF exactly at end of file) are required.
* H accept any unknown opcode during resync. **Rejected**: restricted to opcode < 0x100 and length <= 256 (s12's
  0xFA record has length 6).
* Remaining silent loss on s11: a flipped row/col byte moving a cell onto another cell (indistinguishable from the
  deliberate double write in s12) - documented, needs an organizer answer (Q5).

### EBCDIC-DUMP (s20-s22)
* H1 data record = 44 bytes after RDW. **Failed**; type char + 43 bytes (RDW length 48).
* H2 file = plain RDW stream. **Partly failed**: s21 is blocked (BDW 4 bytes before each block).
* H3 dob = packed `YYYYMMDD`. **Corrected**: 5 bytes = `0YYYYMMDD` + sign nibble F.
* Trailer credits total equals sum of credits (402 on s20, 546 on s21) - used for `checksum_mismatch`.


* M1-5 (2026-10-16): added RDW/BDW length and reserved-byte corruption,
  trailer count/credits mismatch, inner/outer truncation, malformed short
  trailer, invalid packed fields/date, B/D negative balances, unknown types,
  strict detection and direct decoder safety tests.
* Found and fixed: empty packed-decimal input raised IndexError; trailer code
  parsed slices before checking length. Record lengths are now checked first,
  and packed parsing returns None on empty input.
* Failed boundary hypothesis: recognizing the next BDW required its first RDW
  to be intact. A damaged first RDW made the previous block swallow that whole
  block. Known payload sizes/content now independently establish the boundary.
* Descriptor damage resynchronises instead of abandoning all subsequent records;
  recovered records under a damaged BDW are unverified. Credits disagreement
  marks every candidate record unverified because the culprit is unknown.
* RECFM F feasibility review: no supplied fixture establishes LRECL/padding, so
  guessing fixed boundaries would invent evidence. Both unframed mixed-length
  and synthetic padded payloads are explicitly rejected by detection tests.
* Final review added 384 seeded compound-damage cases. Across M1, the final
  suite has 82 passing tests and reference comparison remains 7/7.
* Validation: 75 tests passed with Python 3.12.14; reference comparison 7/7;
  s20/s21 remain ok and s22 remains partial with one truncation root cause.


* Review/refinement pass (2026-10-16): invalid DOB in the next VB block's first
  student made the preceding BDW look invalid and lost both students in that
  block. Boundary proofs now use framing instead of semantic student validity.
  Corrupt first-RDW reserved bytes also preserve the intact sibling.
* Direct-only invalid-header-date tests hid a dispatch failure: end-to-end
  salvage returned UNKNOWN with zero students. Added bounded independent
  record evidence plus engine/CLI regressions and strict negative controls.
* Independent synthetic V/VB fixtures exposed another generalization issue:
  printable accented cp037 names were rejected by ASCII-only credibility.
  Printable accents are now accepted, while control-corrupt fields are null
  and unverified. Tests also guard bounded detection and payload-scan work.

### CVT (s18-s19)
* H1 signature at 0x21. **Failed** (detection missed every file); it starts at 0x1E (`PRG formatted ...`).
* H2 ASCII-style letter case. **Failed**: 0x41-0x5A are lower case and 0xC1-0xDA upper case in PETSCII.
* H3 modified year = byte + 1900 (s18 `0x5B` -> 1991; s19 `0x65` -> 2001). Confirmed on s18.
* VLIR index pair semantic: (blocks, bytes used in last block), `(0,0xFF)` = unused slot.

* M2 sweep: a corrupted VLIR index byte (e.g. s19 slot 0 byte count 20 -> 1) returned `ok` with a 1-character record.
  The padding convention (NUL after the declared count, confirmed on all three s19 records) now detects it.
* A corrupted `declared_blocks` made an intact file look truncated. For VLIR the index total plus the file size now
  decide which field is wrong; for SEQ no second witness exists, so it stays `truncated` / lossy excess.
* H map `\` `^` `_` to PETSCII pound/arrows. **Rejected for now**: no sample uses them; graphics stay U+FFFD and the
  record is flagged rather than guessed.

### PAK / WAD (s23, s24)
* Standard layouts; directory ends exactly at EOF in both. WAD names carry garbage after the NUL (ignored).

* M3-1: independent fixtures and sample mutations now cover huge counts,
  duplicates, nested overlaps, header/directory overlap, empty markers, magic
  variants, incomplete directories and trailing bytes. Intact s23/s24 hashes
  and statuses are unchanged.
* Direct WAD decoding previously raised UnicodeDecodeError for non-ASCII magic;
  both archive decoders now validate their magic without raising.
* Physical count bounds did not bound repeated overlapping payload hashes.
  Exact aliases now share digests, while unique ranges share a 4x-input byte
  budget. Instrumented tests prove memoryview hashing and bounded byte work.
* Rejected pairwise overlap reporting as quadratic in time and output size.
  A sorted interval sweep retains ambiguous entries and marks each component.

### WPD / BRAVO (s14-s17)
* WPD encryption key sits at 0x0C and is 0 in both samples; hint says some files are protected -> non-zero
  = `unsupported`. s15 declares text up to byte 223 in a 136-byte file => truncated.
* 0xAA treated as a soft hyphen (dropped) - unverified guess.
* BRAVO trailer: 15 and 17 bytes after 0x1A; could not derive a consistent run record from two samples,
  so it is intentionally not decoded (bonus field).

* M3-2: original libwpd WP5 framing evidence rejected the old blanket
  C0-CF=3, D0-DF=4, E0-EF=6 and F0-FF=size+5 hypotheses. Only C3/C4 were
  sample-backed. Individual fixed widths and mirrored variable framing are
  implemented independently; payload text is never guessed after framing loss.
* The kit advertises version 2.0 but uses WP5-style gates and a custom text-end
  word. Rejected general support for unrelated WPC product/version profiles.
* A valid delimiter does not prove a group's contents are formatting only.
  Unseen semantic groups now report unknown_record and taint only the affected
  paragraph. C0 character tables remain unsupported; no third-party tables copied.
* M3-3: stricter BRAVO negatives reject DOS EOF text, text/NUL-only suffixes,
  short prefixes and malformed marker framing. CR empty paragraphs remain.
  High-byte/control text is replaced only during independently identified
  direct salvage, with explicit uncertainty; detection does not guess a codec.
* Uniform run-record hypotheses still do not explain both BRAVO trailers.
  The optional format_runs bonus is deliberately omitted.
* Dense CR text exposed output expansion despite the input-byte guard. Both
  document decoders now bound records (100,000) and text (8MiB), with explicit
  loss reports. Operation-count tests verify parsing stops at the budget and
  skips intact large functions without scanning payload characters.

### Hardening findings (mutation suite over all 30 samples)
* Flipping the LIBRA header encoding flag re-decodes text under another code page while record checksums
  still pass -> invariant restricted to non-text fields (text can legitimately differ).
* A CRC-failed LABLOG channel table made later (CRC-valid) samples report wrong calibrated values as
  verified -> those samples are now `verified:false`; likewise when the header CRC fails (time_ms).
* Damage offsets could point past EOF (CVT cut inside block 1) -> clamped to the file size.
* A corrupted LIBRA length byte swallowed the next intact record -> field-based recovery + rescan.

* M3 platform: corrected the handoff's stale auto-discovery claim; the engine
  previously used a manual registry. Public-module discovery, private template,
  import isolation and invalid-score/result tests now support controlled
  extension without editing the registry. New format names still need the
  integrator's contract-vocabulary change.
* Fixed the launcher's missing executable bit. Added regular-file-only reads,
  bounded size checks, replacement checks, atomic output and strict JSON/result
  shape checks. Tested permission errors, FIFOs, input/output symlinks, hostile
  names, nonfinite output and output failures without stopping siblings.
* Invalid-byte filename JSON roundtrips via escapes. This macOS filesystem
  rejects creating such a filename (EILSEQ); the end-to-end test is skipped
  here and exercised on Linux CI. Serialization itself is tested everywhere.
* Found irreconcilable naming edge cases: a 255-byte basename plus `.json`
  exceeds the filesystem limit, and source basename `report` collides with the
  combined report. These now report failure instead of silently stopping or
  overwriting a per-file result with a successful claim.
* Resource review rejected a common records-only cap: WKS accumulates cells in
  local dictionaries, LABLOG has metadata events, and aliased VAULT compressed
  payloads expand independently. Conservative preflight estimates now bound
  those adapters without editing M1/M2 files; refusals are explicit.
* Detection itself needed a guard: damaged large LABLOG headers could allocate
  the lazy CRC index before decoding was refused. Oversized legacy detection
  now uses a 64KiB prefix; an independent test verifies the full file never
  reaches that detector. UNKNOWN analysis is separately prefix-bounded.
* Cross-review found `REPORT`/`Report` also alias the combined report on
  case-insensitive volumes. Actual output file identity now detects reserved
  aliases and previously produced output collisions in constant-time lookup;
  the first result is preserved and later conflicts are explicitly failed.
  Tests cover both filesystem case policies and an output alias introduced
  between sibling writes.

* M3-5 evaluation: deterministic 10/50/90% truncation, one-byte-short,
  midpoint XOR and centered zero-block variants cover all 30 samples. The
  persisted manifest records hashes/parameters and rejects altered variants.
  Seven organizer references are scored independently; remaining recognized
  samples use verified pristine output as a clearly labeled regression baseline.
* Measured 180 variants, 173 changed and 7 no-ops (excluded from summary rates),
  zero decoder crashes. Organizer-reference recovery: 251/366 keys, 227/366
  complete records, five false verified records. Regression-only: 488/789 keys,
  458/789 complete records, five false verified. Unknown originals stayed
  UNKNOWN in all 24 changed cases; zero-record recovery rates are null.
* False verified cases are visible rather than hidden: reference cases are
  CVT/VAULT/WKS; regression cases include EBCDIC/VAULT and archive payload hashes.
  Structural consistency cannot detect every plausible in-bounds corruption
  without an integrity checksum. This corpus does not predict hidden judging.
  Full measured ledger: reports/m3-evaluation.json; rerun tools/evaluate.py.

* M3-6 release validation: 327 tests run on Python 3.12 (326 passed; one macOS filename
  fixture skipped because APFS rejects invalid UTF-8 names); Linux CI passed
  all 327 with no skip. Organizer references match 7/7. Native and Docker runs
  over all 30 samples produced31 byte-identical JSON files under --network none,
  a read-only root, dropped capabilities and an unprivileged user. The same
  parity check also passed on the integrated origin/master baseline 9dc9754.
* The pinned Python base was preloaded during development. Dockerfile RUN steps
  build with networking disabled; runtime/tests introduce no network dependency.
  GitHub workflow repeats tests, evaluation and isolated Docker parity.
* Branch protection could not be enabled: the authenticated collaborator has
  push access but GitHub reports admin:false/maintain:false. Reviewed-PR-only
  workflow remains required; an owner must configure server-side enforcement.

## 2026-10-16 — release 0.1 preparation

* Isolated release/0.1 starts from reviewed master 9679465. Release tags and
  downloaded artifacts do not merge this branch or change master.
* Earlier internal tool version 0.2.0 had no published release. The first
  public release is 0.1.0, with a separately versioned 0.1.0-rc.1 candidate;
  one VERSION value supplies CLI and artifact metadata. Help/version flags
  preserve the always-zero recovery exit behavior.
* Removed optional report-row notes (organizer Q2 unresolved): exact required
  keys remain, and operational details are printed to stderr.
* Chose stdlib-only portable/installer archives. Rejected third-party binary
  bootloaders for this release because the agreed runtime remains stdlib-only.
  Installation requires supported Python already present; no automatic network
  download, GUI, global system install, or shell-profile modification is added.
* Build inputs come from clean committed Git files; archives have fixed metadata,
  exact source commit, complete adapter package, manifests and SHA-256 sums.
  Installer integrity/ownership checks prevent overwriting unrelated files;
  rollback and managed uninstall are independently tested.
* Python ZIP extraction can discard executable bits even when stored in the
  archive; source installation guidance includes chmod+x fallback.
* Windows CMD launchers need explicit handling of Unicode paths and percent
  expansion. The installer quotes paths, disables delayed expansion, switches
  to UTF-8 for invocation and restores console encoding/status afterwards.
* New release checks compare extracted-source, portable and installed output
  from unrelated working directories on all 30 fixtures, plus seven references,
  ten adapters, strict keys, version agreement, fixture hashes and managed
  removal. Python audit hooks deny socket use during checks; these are not
  advertised as an operating-system network sandbox. Docker uses --network none.
* Initial local validation: 359 tests run (358 pass, one APFS filename skip),
  references 7/7. Platform jobs record independent evidence before publication.
