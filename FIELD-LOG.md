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

### WKS (s11-s13)
* Record stream per the public Lotus layout validated on s11 expected. s12 is a stress file: out-of-order
  cells, a cell written twice (kept last), blank formatted cell, unknown opcode 0xFA, named range.
* H number_format must be emitted for every non-default format. **Rejected**: s11 expected has none for
  fmt 0x22 cells, so only date/time formats are emitted.

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

### PAK / WAD (s23, s24)
* Standard layouts; directory ends exactly at EOF in both. WAD names carry garbage after the NUL (ignored).

### WPD / BRAVO (s14-s17)
* WPD encryption key sits at 0x0C and is 0 in both samples; hint says some files are protected -> non-zero
  = `unsupported`. s15 declares text up to byte 223 in a 136-byte file => truncated.
* 0xAA treated as a soft hyphen (dropped) - unverified guess.
* BRAVO trailer: 15 and 17 bytes after 0x1A; could not derive a consistent run record from two samples,
  so it is intentionally not decoded (bonus field).

### Hardening findings (mutation suite over all 30 samples)
* Flipping the LIBRA header encoding flag re-decodes text under another code page while record checksums
  still pass -> invariant restricted to non-text fields (text can legitimately differ).
* A CRC-failed LABLOG channel table made later (CRC-valid) samples report wrong calibrated values as
  verified -> those samples are now `verified:false`; likewise when the header CRC fails (time_ms).
* Damage offsets could point past EOF (CVT cut inside block 1) -> clamped to the file size.
* A corrupted LIBRA length byte swallowed the next intact record -> field-based recovery + rescan.
