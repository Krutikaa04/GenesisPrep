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

* Issue #17 VAULT slice (2026-10-16): independent 2,881,456-byte binary and
  2,377,456-byte text archives were refused by the 2MiB ceiling; a 98,416-byte
  low-expansion RLE archive was refused by the 127x worst-case projection.
  Replaced those VAULT-only assumptions with exact, allocation-free expansion
  counts and type-aware work/output charges. All three now recover their exact
  48/48/80 independently known records without damage. Work/output caps stay
  16MiB; other formats keep their current limits.
* Negative controls: repeated raw/RLE/XOR-RLE aliases, late invalid RLE escapes
  after expanded prefixes, and record/output amplification still refuse before
  payload decoding. Invalid streams must charge the prefix they could allocate;
  treating an invalid stream as zero work would be unsafe. A deterministic scan
  guard proves later aliases are not scanned after the work budget is exhausted.
  See reports/issue-17-vault-profile.json and docs/VAULT-LARGE-FILES.md for measured
  times, traced allocation, exact bounds and their limitations.

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
* Issue #18 extends that earlier C0 policy narrowly: source revision
  a3bd5291e19006eb8e7edaead01fed1baf2aedf7 establishes field order
  `C0 character charset C0` and the printable ASCII rule for set zero. Added
  known-answer fixtures before implementation for all 95 printable characters;
  all other character sets and set-zero nonprintables still produce U+FFFD,
  lossy unknown_record and unverified text. Rejected the upstream converter's
  whitespace fallback, since an unknown glyph is not a proved space.
* At that same revision WP5SingleByteFunction identifies 8C/90/99 as returns,
  93/94/95 as spaces, AB as a visible hyphen, and AC/AD/AE as U+00AD soft
  hyphens. Literal known answers cover each code and paragraph/page indices.
  The kit AA-drop/A0-space assumptions disagree with general WP5 semantics;
  retained them explicitly instead of changing official sample output.
* WP5PageFormatGroup plus WP5FileStructure establishes four exact D0 layout
  payloads: margins 01/05 (8 bytes), spacing 02 (4), justification 06 (2,
  old/new values 0..4). They contain no body text. Literal frames precede the
  implementation and check untainted surrounding text. Unknown sizes/enums,
  subgroups and embedded-text functions remain lossy/unverified; framing and
  byte/record budgets take precedence over semantics. Payload control bytes,
  every partial C0/justification boundary and corrupt closing gates are tested.
* Rejected blanket C1/C2 skipping: their tab/indent interpretation depends on
  paragraph context, so treating them as decoration would silently lose tabs.
  Deferred vendor character tables and nested document functions until their
  semantics have independent fixtures. Sources are pinned in the WPD spec;
  no third-party code/tables/dependencies added. This branch does not touch
  shared engine/model/CLI/helpers, budget policy or other format decoders,
  leaving issue #17's M1/M2 large-input work independent.
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
* Issue #15 (supersedes the historical text-only recovery experiment below):
  CR paragraph count is not BRAVO identification evidence. At baseline 4befda0,
  `tools/evaluate_bravo.py` measured 20 false BRAVO identifications among 32
  independently constructed ordinary memos, tables and logs, including DOS EOF
  and short-control suffixes. Removed the 0.55 heuristic; the same controls now
  yield 32 UNKNOWN and zero false BRAVO identifications. The current reproducible
  ledger is reports/bravo-identification.json. No general false-positive rate is
  inferred from this small, purpose-built corpus.
* Direct BRAVO library recovery previously silently verified complete paragraphs
  even when identity was unproved. It now applies the detector's checks and
  marks every paragraph unverified on failure, using existing contract issues
  and damage kinds. No shared engine/CLI interface change or force mode needed.
  A constructed lost-CR fixture verifies that clean earlier paragraphs survive
  while subsequent paragraph indices remain explicitly uncertain.
* Measured tradeoff with tools/evaluate.py: BRAVO regression recovery 41/60 ->
  27/60 keys, complete records 34/60 -> 21/60, coverage 9/12 -> 6/12, zero false
  verified records and zero crashes in both runs. The three newly rejected
  fragments lack sufficient marker/trailer evidence. All four midpoint-flip /
  zero-block cases retain recovery. These are decoder-derived regression
  baselines, not independent paragraph truth. Seven organizer references remain
  unchanged. Trailer cuts leaving sufficient evidence can still report ok;
  trailer completeness, formatting runs, and plausible ASCII corruption remain
  unproved. The earlier log records the experiment and its rejected tradeoff.

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

* False-verified sweep (from reports/m3-evaluation.json, 10 cases). Fixed 5: VAULT text that is not valid UTF-8
  (flipped byte or zeroed RLE data inside a size-preserving block; text is UTF-8, confirmed on s09) is now
  unverified + invalid_value; WKS formulas not ending in the 0x03 terminator token (all kit formulas do) and
  non-ASCII labels (latin-1 is an assumption) are unverified + invalid_value. Not fixable, kept visible: CVT 0xCF
  flipped to 0x30 reads as a valid "0"; PAK/WAD payload hashes (no stored hash or checksum); EBCDIC pad byte
  flipped to a valid cp037 character (accented letters are legitimately allowed). Organizer-reference false
  verified 5 -> 1, regression baseline 5 -> 4.

* BRAVO recovery (measured with tools/evaluate.py): BRAVO regression recovery 10/60 -> 41/60 keys, 34/60 complete, 0 false
  verified. Cause of the old failures: recognition needed a fully printable text prefix, so one flipped byte or a
  zeroed block mid-text made the whole file UNKNOWN even with the trailer intact (4 of 12 cases). Fix: trailer + marker
  prove the layout, text only needs to be >= 70% text bytes; paragraphs after damage are unverified because lost CRs
  shift paragraph numbers. Truncated files (no marker/trailer) are now recognised at confidence 0.55 from CR-only
  ASCII text (>= 3 paragraphs, >= 32 bytes, no LF, < 64 KiB): s16 cut at 50%/90% and s17 at 90% decode; the 10% cuts
  (no CR yet) and s17's 50% cut (only 2 CRs) stay UNKNOWN. Trade-off: other CR-only text would be misidentified.

## 2026-10-16 — M3 issue #8 development baseline

* Started issue-8-release-baseline from origin/master 31b40d8. Ported release
  tooling from immutable v0.1.0 rather than resetting the diverged release/0.1
  branch. Newer BRAVO recovery, M1/M2 improvements and symlink capability tests
  are preserved; no format decoder or official fixture is changed by this work.
* Restored portable/source/installer builds, package verification, installation
  guidance, module entry point and help/version flags. One VERSION literal now
  identifies the unpublished source as 0.2.0-dev across CLI, reports and builds.
* Operational report notes go to stderr so report rows contain only the required
  keys. Existing filesystem failure tests assert diagnostics rather than extra
  JSON keys; no failure-handling coverage was removed.
* Test discovery supplies the current count. The 370-test figure describes the
  published v0.1.0 snapshot, not this checkout. Release validation also runs on
  PRs into master and builds artifacts without publishing anything.
* Initial integrated validation on macOS/Python 3.12: 375 tests run, one
  filesystem skip, all other tests pass; organizer references remain 7/7.
  The newly discovered count includes the release tests and newer BRAVO tests.
  Recomputed evaluation equals the current-master ledger exactly (180 variants,
  173 changed), so restoring packaging has not changed decoder measurements.
  Local offline Docker build/run also matches all 31 native JSON files exactly.

## 2026-10-16 — M3 issue #13 CLI diagnostics and presentation

* Started codex/issue-13-cli from integrated master f089bc1, including the
  schema-1 evidence model. No decoder or official fixture changes.
* Established exit policy before implementation: recovery remains always 0;
  validation uses 0 complete, 1 failed/error, 2 usage, 3 unavailable. Added
  argparse modes, plain recovery tables, read-only doctor and historical
  schema-1 evidence presentation with separate baseline/outcome tables.
* Runner issues #10–#12 are still separate. Missing implementations explicitly
  return unavailable without creating output. Documented run(ValidationRequest)
  integration; fake runners test dispatch/persistence without duplicating their
  comparison, test-accounting or benchmark algorithms.
* Historical evidence retains recorded environment/version/time and resolves
  artifact references against its saved location. Absent/empty metrics never
  turn into passing measurements or arbitrary-input accuracy percentages.
* Fresh evidence destinations protect inputs and prior recovery/evidence
  output; resolved symlink aliases, existing destinations, reserved filenames,
  runner exceptions, terminal controls and limited encodings have regressions.
* Local Python 3.12 validation: 414 tests run, one platform skip, all others
  pass; organizer references 7/7. Offline Docker parity remains 31/31
  byte-identical JSON files. Portable-mode diagnostics run outside the source
  checkout in a focused regression; missing resources remain unavailable.
* First PR CI passed macOS/Linux/build/Docker but exposed a Windows test
  assumption: its temporary root uses an 8.3 alias while the CLI resolves the
  saved evidence path. Corrected the artifact-path assertion to use the resolved
  evidence parent, preserving the intended relative-path check and behavior.
* Final usage review added malformed boolean-mode assignments (for example,
  --verify=true) to diagnostic usage-error handling: exit 2 rather than legacy
  recovery's exit 0. Existing recovery usage semantics are retained.

## 2026-10-16 — M3 prerequisite: fresh source-test execution

* Issue #10's full-suite check exposed an existing #11 false-pass risk: a
  same-size rewrite inside one timestamp tick could reuse cached passing test
  code. This is a runner correctness defect, not a reason to skip/weaken tests.
* Give each worker a fresh temporary PYTHONPYCACHEPREFIX, bypassing existing
  caches without altering sources or global interpreter configuration. Added a
  known-answer regression seeding stale passing bytecode, rewriting a failing
  source at the same size/timestamp, and requiring the current failure outcome.

## 2026-10-16 — M3 issue #10 reference runner

* Started codex/issue-10-reference from master 3eb541d. Added the isolated
  reference service with #13 run(request) integration, standalone/API entry
  points and saved actual outputs, original reference snapshots, structured
  differences, dynamic counts and schema-1 provenance/artifact hashes.
* Moved matching into the runtime module and imported its compatibility API
  from tools/compare_expected.py. Existing semantics remain deliberate:
  optional partial identities, requested fields only, last duplicate identity,
  any_of damage kinds; lossy/offset/detail are not compared by the old tool.
* Missing/empty/malformed resources cannot produce a passing empty run. Strict
  loading rejects traversal, duplicate JSON keys, nonfinite values and malformed
  matching/damage shapes. Read budgets are explicit. Input hashes and decoding
  use the same snapshots; incomplete resource collection leaves hash/counts
  unknown. No decoder, fixture or recovery-contract edits.
* Evidence creation refuses protected/aliased directories and any nonempty
  destination, preserving existing recovery reports and earlier evidence.
  Artifacts use exclusive numeric paths with relative references and SHA-256.
* Focused known-answer tests cover official 7/7 and s04's optional partial
  record, mismatch locations, legacy matching behavior, malformed/missing
  resources, bounds, immutable inputs, aliases and portable execution outside
  the checkout with explicit Unicode/space paths.
* Added explicit incomplete-comparison evidence for decoder exceptions and
  unusable actual matching keys, retaining any actual result instead of
  manufacturing agreement. Snapshot-mutation regression confirms hashes
  describe the same bytes that were decoded.
* After the isolated stale-bytecode prerequisite fix, the ordinary Python 3.12
  command passes without a bytecode environment workaround: 451 tests run,
  one platform skip; organizer comparison remains 7/7.
* Canonical release build/check passed on Python 3.12: extracted-source,
  portable and installed recovery produce 31 identical JSON files with all
  7 references. The canonical portable --verify mode also passes 7/7 using
  an explicit external kit from an unrelated working directory.
* Live CLI/standalone presentation now resolves artifact references against
  the saved envelope directory, as historical presentation already did; added
  a regression for usable absolute paths to actual/comparison artifacts.
* Final live-path regression brings discovery to 452 tests (one platform skip),
  all other tests pass without environment workarounds; references remain 7/7.

## 2026-10-16 — M3 issue #13 service integration completion

* Started codex/issue-13-integration from merged master ff99ba0. Added the
  missing run(request) test-service adapter; it delegates to #11's existing
  run_tests without duplicating discovery, isolation, recursion guards or
  outcome accounting. Shared CLI persistence/exit behavior and recovery JSON
  stay unchanged. Missing-source guidance now names --source-dir for the CLI.
* Doctor discovers all real runner adapters and also checks benchmark scoring
  file presence. It does not execute tests or import external scorer files.
* Added real-service CLI regressions for passing/skipped/expected-failure
  counts, failures/errors/unexpected successes, missing/empty/import-broken
  suites, historical presentation, artifact paths, protected output and
  portable execution with Unicode/space paths. Tiny suites avoid recursive
  execution of the project suite. Reference and benchmark modes are also
  exercised through the shared CLI with separate evidence sections.
* A new benchmark smoke-test expectation initially labelled a supplied
  UNKNOWN organizer answer no_record_baseline. Corrected it to the actual
  organizer_reference baseline; zero record denominators remain unavailable.
  No production scoring rules or existing assertions were relaxed.
* Python 3.12 validation: 24 focused CLI tests and all 473 discovered tests
  pass (one platform filesystem skip); organizer comparisons remain 7/7.
  Real checkout doctor exits 0 with all ten adapters, three services, kit and
  scorer resources present. No decoder or official fixture changes.
* Canonical portable --test surfaced two source-suite assumptions: bare doctor
  intentionally cannot infer an external kit, and the reference protection
  fixture must explicitly name its external source kit. Both tests now supply
  ROOT/source_dir while preserving their availability/protection assertions.
  The first failed protection check created a new-proof directory under the
  local official kit; removed exactly its six generated artifacts and empty
  directories, restoring the fixture tree. No tracked official bytes changed.

## 2026-10-16 — M3 portable demo validation and shared entry point

* Started codex/demo-portable-integration from master 9033c48. Fixed the
  source-protection test's checkout-location assumption by explicitly selecting
  ROOT when asserting protection of that external kit. The assertion remains;
  a portable app cannot infer an unrelated test checkout from its archive path.
* Added a portable-runtime regression that copies support sources/scorers into
  a temporary external kit and executes the existing protection assertion.
  It confirms archive imports, immutable source contents and no demo-proof
  output. Any future failed protection test stays inside temporary data rather
  than attempting to write into the real workspace or official fixtures.
* Added salvage --demo by delegating the original arguments to the existing
  demo parser; no second option grammar. Help, guided mode, historical/skip
  selections and exit status remain with that parser. Mixed modes/unknown
  options are usage errors; -- preserves literal recovery folder names.
* Demo live tests now use the same dispatcher/adapter as reference and benchmark
  steps, replacing the pre-#13 direct service workaround. No decoder, recovery
  contract, source-kit inference or application version change.
* Focused demo checks pass (15 tests), including real shared CLI execution,
  immutable generated copies, failure/skip/history propagation, parser conflicts
  and portable external-source protection.
* Ordinary Python 3.12 discovery passes all 489 tests (one platform filesystem
  skip), with organizer comparison still 7/7. Literal --demo recovery paths,
  shared help/usage and legacy recovery output remain covered.

## 2026-10-17 — M3 issue #17 selective large-input budgets

* Preserved VAULT's merged work/output, alias and RLE amplification safeguards.
  Remaining format helpers are isolated into per-format PRs. Shared enabling
  code keeps original refusals on absent/broken helpers, uncertain framing or
  exhausted budgets. No decoder semantics, output contract or official fixture
  change; issue #19 remains outside scope.
* Rejected a blanket increase of the legacy byte ceiling. New helpers must
  count physical selected ranges/items and establish their own bounded path
  before the ordinary decoder runs. Original small-input behavior remains.
* Per-format fixtures, independent expected values, rejected declarations and
  exact limits are documented in docs/*-LARGE-FILES.md and paired measured
  ledgers reports/issue-17-*-profile.json. Baseline profiles explicitly replay
  the original coarse refusal with optional helpers disabled and unchanged
  decoders; paired input hashes must agree. Input allocation is excluded from
  traced parsing+JSON measurements. These are not process-RSS/time promises.
* Common scan/work/output/item bounds and refusal behavior are documented in
  docs/ISSUE-17-LARGE-INPUTS.md. Trusted helper imports and failures are tested
  to default to refusal; no runtime dependency, network or input plugin added.

## 2026-10-17 — M3 dynamic reference accuracy presentation

* Extended the existing reference runner, rather than guessing accuracy from
  successful decoding or verification flags. New input/answer snapshots produce
  per-file and summed record recovery, supplied-field accuracy and precision;
  missing, wrong, unexpected and optional records remain separate counts.
* Record correctness requires all supplied fields to exist and agree and the
  format to match. File agreement retains the organizer's original semantics.
  Optional partial identities are excluded; unreferenced files are not scored.
* Rejected duplicate-identity collapse as an accuracy policy: it can hide wrong
  records. Ambiguous identities or multiple answers for one file retain legacy
  file comparison but explicitly make aggregate record accuracy unavailable.
* Unknown/empty denominators never become 100%. Historical evidence keeps its
  recorded counts; older evidence with no record measurements says unavailable.
  No decoder, recovery JSON, official fixture, dependency or issue-19 work changed.

## 2026-10-17 — M3 terminal dashboard and visual demo

* Added ASCII dashboard panels, batch-status bars with exact counts, measured
  ratio bars with denominators and explicit unavailable states. File counts
  are never labelled accuracy; test outcomes remain counts. Narrow tables
  switch to labelled rows; panel text wraps without dropping stored data.
* Guided demo uses actual saved records in field/uncertainty cards, scaled
  truncation/checksum diagrams with exact byte counts/offsets, damage cards,
  compact benchmark baseline tables and a final step-state board. Full evidence
  stays linked. Historical measurements keep their own provenance/version/time.
* Interactive borders can use colour; NO_COLOR, dumb terminals, redirection
  and older Windows consoles remain plain. Data controls remain escaped.
  Rejected fake progress/accuracy indicators: RUNNING is a state, not an ETA.
* No decoder, recovery output contract, official sample or dependency changed.
  This is presentation work; issue #19 finalization remains outside scope.
