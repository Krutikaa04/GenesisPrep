# Field Log — the readable edition

> A plain-language companion to [`FIELD-LOG.md`](../FIELD-LOG.md). Nothing here is new research: every row
> comes from the original log, reorganised into tables. The original stays the official record
> (it is append-only, per `AGENTS.md`). If this page and the original ever disagree, the original wins.

## 1. What is the field log?

It is the team's **lab notebook**. Nobody gave us documentation for these old file formats, so for each one we
guessed how a field is stored, tested the guess against the 30 sample files, and wrote down the result,
including the guesses that were wrong.

| Document | Answers the question | Style |
|---|---|---|
| `FIELD-LOG.md` | "How did you find out?" | The journey: every guess, in order |
| `FORMAT-SPEC.md` | "What is the layout?" | The result, marking each field *confirmed* or *assumption* |
| **this page** | "Can I follow the story quickly?" | The journey, as tables |

### How to read the verdicts

| Word | Meaning |
|---|---|
| **Confirmed** | Matched the organizers' answer file and/or a checksum that validates on every sample |
| **Failed** | We tested it and the data disagreed |
| **Partly failed / Corrected** | Right idea, wrong detail. We adjusted it |
| **Rejected** | We decided not to do it because it would be a guess or too risky |
| **Open** | We could not settle it from the evidence. It is documented as an assumption |

**Naming:** `H1, H2…` = hypotheses. `s01…s30` = the sample files. `M1/M2/M3` = the three team members' areas.
`Q1…Q7` = open questions for the organizers.

---

## 2. The six best stories (for mentors)

1. **The date that was 20 years off (LABLOG).** Reading the start time as a normal Unix timestamp gave
   1972, with the right month, day and time but the year 20 too low. Hypothesis: the clock starts at
   1990-01-01. That gave `1992-10-11T05:07:43Z`, exactly the organizers' answer.
2. **The 8-bit sum that matched 22 out of 22 (LIBRA).** We tried many checksum functions over many byte
   ranges. Only "add up the bytes from `flags` to the byte before the checksum" worked on every record.
3. **The key that moves (VAULT).** One fixed XOR key made no text readable. A key that *advances by one for
   each byte* (`key + position`) turned a row of 40 `-` characters into a counting sequence, which proved it.
4. **The jump that said "ok" while 7 of 9 cells were gone (WKS).** Flipping one length byte made the
   decoder leap 257 bytes, land by luck on a real record boundary, and report `ok`. That is exactly the kind
   of silent loss we hunt for. It is now fixed.
5. **Fewer false positives over a better score (BRAVO).** A looser recogniser scored well (41 of 60), but a
   test on 32 ordinary memos and logs found 20 of them wrongly identified as BRAVO. We removed the
   heuristic. Recovery fell to 27 of 60, with zero false identifications. We chose trust over numbers.
6. **The guess we refused to make (several formats).** We did not guess a key, a missing index, fixed-record
   boundaries or unknown character glyphs. Each time, the log says why.

---

## 3. Format by format

### 3.1 LIBRA-98 (library database, s01–s04)

| # | What we guessed | Verdict | What the data said |
|---|---|---|---|
| H1 | `created` is a Unix time | **Failed** | `0x5A8B2543` gives 2018. Expected 1998-10-03T11:20:22 |
| H2 | `created` is two DOS words, date first | **Confirmed** | Date `0x2543`, time `0x5A8B` on s01 |
| H3 | `A5 2B 00` is marker plus 16-bit length | **Failed** | The length is one byte. The next byte is flags (record 2: `3E 01`, length 62, flag 1 = checked out) |
| H4 | Year is stored directly | **Failed** | `0x018D` is 397. Add 1500 to get 1897 |
| H5 | Which checksum protects a record | **Confirmed** | sum8 from `flags` to just before the checksum matched 22/22. The trailer is a 16-bit sum of everything before `END!` (3/3). CRC variants did not match |
| H6 | `data_offset` is always 16 | **Failed** | s03 has 40, because it carries a vendor string (`LIBSYS/98 REL 2.1`) |
| H7 | Text is always code page 437 | **Failed** | s03's bytes `0x92`, `0xDF` only make sense as cp1252. Header flag bit 0 selects the code page |
| — | Flag bits 1–2 mean "deleted" and "reference only" | **Open** | Cannot be confirmed from the two reference files (question Q1) |

**Hardening found later**

| Problem found | What we did |
|---|---|
| A too-large length byte skipped field recovery and swallowed later good records | Recovery by fields now runs before the "file ended" decision |
| A partial trailer checksum caused a false `count_mismatch` | Suppressed. A truncated file reports only `truncated` |
| Duplicate IDs | Kept, flagged, never silently merged |
| A stray `END!` inside garbage stopped recovery early | Resync now tells it apart from a real, checksum-valid trailer |
| Flipping the header's code-page flag changed the text while the record checksums still passed | Non-ASCII text is marked unverified when the trailer can't prove the header. No other code page is guessed |
| A bad data pointer hid good records | The pointer is repaired only when exactly one candidate explains every record and the file checksum. Ambiguous cases are refused |
| Resync recomputed checksums from the start each time (slow on repeated damage) | A running checksum is carried along, so the work is now linear |
| Offset repair could pick the wrong earlier chain (found in cross-review) | Repair never overrides an intact declared chain |

### 3.2 LABLOG (instrument log, s05–s07)

| # | What we guessed | Verdict | What the data said |
|---|---|---|---|
| H1 | Start time is Unix time | **Failed** | Gave 1972-10-11T05:07:43Z: right month, day and time, year 20 too low |
| H2 | The epoch is 1990-01-01 | **Confirmed** | `1992-10-11T05:07:43Z` matches s05's expected output |
| H3 | Interval is a literal 50 ms | **Failed** | Expected 500. The field counts units of 10 ms |
| H4 | A channel entry is unit (6 bytes) plus two floats (14 bytes) | **Failed** | A block of 24 bytes for 2 channels means 12 bytes each. The unit is 4 bytes |
| H5 | Which checksum protects blocks and header | **Confirmed** | CRC-16/CCITT-FALSE over `type..payload` matched 7/7. The header CRC covers bytes 0..29 |
| H6 | Only raw -32768 means a dropout | **Confirmed** | Raw -20224 is a real value (expected `-10091.5`) |

**Decisions and hardening**

| Topic | What we did |
|---|---|
| Truncated data block | Still dropped. Complete rows alone can't prove integrity without the block CRC (conservative, on purpose) |
| Calibration missing or table failed | Values become `null` and unverified. Raw values are never emitted as calibrated ones |
| Corrupt length value | If rebuilding only the length makes the stored CRC verify, the block is repaired. Six corrupt lengths on s05 had cost 4 of 22 samples |
| Damaged header channel count | Restored only when intact table and sample widths uniquely support it. The failed header CRC is still reported |
| A zero-channel header with a valid CRC | Still rejected |
| Slow CRC search on dense lookalike blocks (almost six seconds at 13 KB) | A lazy interval-CRC index, checked against a plain bitwise CRC |
| Missing golden files for s06/s07 | The tests read header and event facts but don't claim independent proof of the inferred epoch |

### 3.3 VAULT (container, s08–s10)

| # | What we guessed | Verdict | What the data said |
|---|---|---|---|
| H1 | Whole file XORed with one constant key | **Failed** | No key reveals text |
| H2 | `logo.bin` is stored raw | **Confirmed** | Its SHA-256 matches a 20-byte window of s08 at offset 205 |
| H3 | The XOR key advances with position, `(key + i) & 0xFF` | **Confirmed** | 40 `-` characters become a counting sequence |
| H4 | Names have a plain length byte | **Partly failed** | s09 (header flags = 1) also XORs the length byte |
| H5 | Which RLE scheme | **Confirmed** | The 0x90 escape with BinHex rules reproduces `size` on every compressed entry. Other schemes did not |
| H6 | Entry flags: bit 0 = RLE, bit 1 = XOR | **Confirmed** | Matches `compressed` true/false/false |
| H7 | Recover the key by picking the most printable result | **Rejected** | Neighbouring keys tie on short lowercase names, so it would be a guess |
| H8 | Scan for `BL`+id blocks if the index is lost | **Rejected** | Type, flags, names and the size check all live in the index. A block without them can't be graded |

**Limits we documented**

- A key off by one (0x21 versus 0x22) can still give printable text, and **cannot be detected**.
- A flipped RLE flag on a block with no 0x90 byte gives identical data, and only `compressed` differs: undetectable.
- A payload whose length differs from `size` has its `sha256` dropped, since it can only look authoritative.
- Issue #17: large archives (2.9 MB binary, 2.4 MB text, a 98 KB low-expansion RLE archive) were refused by old
  ceilings. Replaced with exact, allocation-free expansion counts. They now recover their 48 / 48 / 80 known
  records. Hostile cases (aliases, late invalid escapes, amplification) still refuse before decoding.

### 3.4 WKS (spreadsheet, s11–s13)

| Topic | Verdict | Detail |
|---|---|---|
| Record stream | **Confirmed** | Follows the public Lotus layout, validated on s11's expected output |
| s12 is a stress file | **Noted** | Out-of-order cells, a cell written twice (last one kept), a blank formatted cell, unknown opcode `0xFA`, a named range |
| Emit `number_format` for every non-default format | **Rejected** | s11's expected output has none for format `0x22`, so only date/time formats are emitted |
| Flipped high length byte of a skipped record | **Fixed** | Decoder jumped 257 bytes, landed on a real boundary and said `ok` with 7 of 9 cells gone. Known opcodes now use their known length when a strict chain follows |
| Two records are enough to resync | **Rejected** | Random bytes can look like two records. Three (or a chain ending exactly at EOF) are required |
| Accept any unknown opcode when resyncing | **Rejected** | Limited to opcode < 0x100 and length ≤ 256 (s12's `0xFA` has length 6) |
| A flipped row/col byte moving a cell onto another | **Open** | Indistinguishable from the deliberate double write in s12. Needs an organizer answer (Q5) |

### 3.5 EBCDIC-DUMP (mainframe tape, s20–s22)

| # | What we guessed | Verdict | What the data said |
|---|---|---|---|
| H1 | A data record is 44 bytes after the RDW | **Failed** | It is a type character plus 43 bytes (RDW length 48) |
| H2 | The file is a plain RDW stream | **Partly failed** | s21 is blocked: a 4-byte BDW precedes each block |
| H3 | Date of birth is packed `YYYYMMDD` | **Corrected** | 5 bytes: `0YYYYMMDD` plus a sign nibble `F` |
| — | Trailer credits total | **Confirmed** | Equals the sum of credits (402 on s20, 546 on s21). Used for `checksum_mismatch` |

**Hardening**

- Empty packed-decimal input used to raise `IndexError`. Lengths are now checked first.
- Damaged first RDW or BDW used to make the previous block swallow the next. Boundaries are now proven by framing, and damaged descriptors resync.
- A credits-total disagreement marks every candidate record unverified, because the culprit is unknown.
- **Rejected:** fixed-length (RECFM F) detection. No sample establishes the record length or padding, so guessing boundaries would invent evidence.
- Accented names in code page 037 are accepted. Control-corrupted fields become `null` and unverified.

### 3.6 CVT (Commodore 64, s18–s19)

| # | What we guessed | Verdict | What the data said |
|---|---|---|---|
| H1 | Signature is at 0x21 | **Failed** | Detection missed every file. It starts at 0x1E (`PRG formatted ...`) |
| H2 | ASCII letter case | **Failed** | In PETSCII 0x41–0x5A are lower case and 0xC1–0xDA are upper case |
| H3 | Modified year is byte + 1900 | **Confirmed** | s18 `0x5B` gives 1991. s19 `0x65` gives 2001 |
| — | VLIR index pair | **Confirmed** | (blocks, bytes used in last block). `(0, 0xFF)` is an unused slot |
| H4 | Map `\` `^` `_` to PETSCII pound and arrows | **Rejected for now** | No sample uses them. Graphics become U+FFFD and the record is flagged |

**Hardening:** a corrupted VLIR index byte once returned `ok` with a 1-character record. The padding convention
(NUL after the declared count) now catches it. A corrupted `declared_blocks` could make an intact file look
truncated, so for VLIR the index total plus the file size decide which field is wrong. For SEQ no second witness
exists, so it stays `truncated`.

### 3.7 PAK and WAD (game archives, s23–s24)

Standard layouts. The directory ends exactly at end-of-file in both samples, and WAD names carry ignored garbage
after the NUL. Hardening covered huge counts, duplicates, nested overlaps, empty entries, bad magic and trailing bytes.

| Problem found | What we did |
|---|---|
| WAD decoding raised `UnicodeDecodeError` on non-ASCII magic | Both decoders now validate magic without raising |
| Overlapping entries could force repeated payload hashing | Exact aliases share digests. Unique ranges share a 4×-input byte budget |
| Pairwise overlap reporting is quadratic | **Rejected.** A sorted interval sweep marks ambiguous entries instead |

### 3.8 WPD and BRAVO (documents, s14–s17)

**WPD (WordPerfect)**

| Topic | Verdict | Detail |
|---|---|---|
| Encryption | **Noted** | The key at 0x0C is 0 in both samples. A non-zero key means `unsupported` |
| s15 | **Noted** | Declares text up to byte 223 in a 136-byte file, so it is truncated |
| Byte `0xAA` as a soft hyphen (dropped) | **Open** | An unverified guess, kept to match the official sample. General WP5 semantics disagree (question Q3) |
| Blanket function-code widths (C0–CF = 3, D0–DF = 4 …) | **Rejected** | Only C3/C4 were sample-backed. Fixed widths and variable framing are now implemented individually |
| C1/C2 skipping | **Rejected** | Their meaning depends on paragraph context, and skipping would silently lose tabs |
| Unseen function groups | **Handled** | Reported as `unknown_record`, tainting only the affected paragraph |
| Character sets other than set zero | **Handled** | Produce U+FFFD, a lossy `unknown_record` and unverified text. The converter's "whitespace fallback" was rejected |

**BRAVO (1970s editor)**

| Topic | Verdict | Detail |
|---|---|---|
| Formatting-run trailer (15 bytes on s16, 17 on s17) | **Open, deliberately skipped** | No single layout fits both samples. It is a bonus field |
| Recognising damaged files | **Improved** | Recovery 10/60 → 41/60 when the trailer and marker prove the layout and text only needs to be mostly text |
| CR-only text counted as evidence | **Reversed (Issue #15)** | 20 of 32 ordinary memos were wrongly identified. The heuristic was removed, giving 32 unknown and 0 false BRAVO |
| Cost of that fix | **Measured** | Recovery 41/60 → 27/60, complete 34/60 → 21/60, with 0 false verified and 0 crashes. These are regression baselines, not independent truth |
| Direct recovery verifying paragraphs without proof of identity | **Fixed** | Every paragraph is now marked unverified when identity isn't proved |

---

## 4. Problems found by attacking all 30 samples (hardening)

| What broke | Fix |
|---|---|
| Header encoding flag flip: the text changed but the checksums passed | The test invariant excludes text fields. Text carries uncertainty |
| A CRC-failed LABLOG channel table made later samples look verified with wrong values | Those samples become `verified: false`. The same holds when the header CRC fails (`time_ms`) |
| Damage offsets pointing past end-of-file | Clamped to the file size |
| A corrupted LIBRA length byte swallowed the next good record | Field-based recovery plus rescan |
| The handoff claimed auto-discovery of adapters, but the engine used a manual list | Auto-discovery was built and tested. New format names still need a contract change |
| Launcher lacked its executable bit | Fixed |
| Unsafe input handling | Regular-file-only reads, size limits, replacement checks, atomic writes and strict result checks. Tested with FIFOs, symlinks, hostile names, non-finite output and write failures |
| A 255-byte file name plus `.json` is too long. A source named `report` collides with `report.json` | Reported as `failed` instead of silently overwriting. Case-insensitive aliases (`REPORT`) handled via actual file identity |
| A damaged big LABLOG header could allocate the CRC index during detection | Detection of oversized legacy files uses only a 64 KB prefix |
| A single "records cap" can't bound work | Per-format preflight budgets. Refusals are explicit, never silent clipping |

### Why recovery numbers appear in the log

| Date and item | Result |
|---|---|
| M3-5 evaluation | 180 variants (173 changed, 7 no-ops excluded), **0 crashes**. Organizer-reference recovery 251/366 keys, 227/366 complete |
| False-verified sweep | 10 cases found. 5 fixed (VAULT non-UTF-8 text, WKS formulas without the `0x03` terminator, non-ASCII labels). Organizer-reference false verified 5 → 1 |
| Cases that can't be fixed | CVT `0xCF` flipped to a valid `0`, PAK/WAD payload hashes (no stored checksum), EBCDIC pad byte flipped to a valid character |
| BRAVO | 10/60 → 41/60 → 27/60 (see 3.8) |

These numbers describe a deliberately damaged corpus. They are not a prediction for hidden judging files.
For current figures, run `python tools/evaluate.py`.

---

## 5. Platform and tooling timeline (M3)

| Date | Work | Notable point |
|---|---|---|
| 2026-10-16 | Issue #8, development baseline | Release tooling ported from v0.1.0. One version string, `0.2.0-dev`, used everywhere. Operational notes go to stderr so `report.json` keeps only the required keys |
| 2026-10-16 | Issue #13, CLI diagnostics and presentation | Exit policy fixed first: recovery always 0. Validation: 0 complete, 1 failed, 2 usage, 3 unavailable. `--verify=true` is a usage error |
| 2026-10-16 | Fresh source-test execution | Found a false-pass risk: stale bytecode could re-run old passing code. Each worker now gets its own bytecode cache |
| 2026-10-16 | Issue #10, reference runner | Saves actual outputs, original references, differences and hashes. An empty or missing set can never count as a pass |
| 2026-10-16 | Issue #13, service integration | Doctor, test runner and benchmark wired to the CLI. The first protection test accidentally wrote into the kit, and was cleaned |
| 2026-10-16 | Portable demo | `--demo` added through the existing parser |
| 2026-10-17 | Issue #17, large inputs | A blanket byte-limit increase was **rejected**. Each format proves a bounded path first |
| 2026-10-17 | Dynamic reference accuracy | Accuracy comes from real answer keys only. Duplicate-identity collapse was rejected. Unknown or empty denominators never become 100% |
| 2026-10-17 | Terminal dashboard and visual demo | Fake progress and accuracy indicators were rejected. "RUNNING" is a state, not an ETA |

**How the number of tests grew:** 327 → 370 (the v0.1.0 snapshot) → 375 → 414 → 452 → 473 → 489, and 596 in the latest live
demo (584 passed, 12 skipped). The test count changes with each branch. Use the live count, not an old figure.

---

## 6. Open questions and known limits

| Item | Status |
|---|---|
| Q1 LIBRA flag bits 1–2 (deleted / reference only) | Assumption |
| Q2 Are extra keys allowed in the JSON? | Unanswered |
| Q3 WPD `0xAA` soft hyphen, `0xA0` spacing, page-break records | Assumption |
| Q4 BRAVO empty paragraphs as records | Assumption |
| Q5 WKS cell written twice: last value or both | Assumption (last kept) |
| Q6 Record with a failed CRC but sound structure: present or absent? | Assumption (present, unverified) |
| Q7 Status when only lossless damage exists | Currently `partial` |
| Formats without a checksum | `verified` means consistent with itself, not proven identical |
| BRAVO formatting runs | Not decoded |
| Branch protection on `master` | Could not be enabled (the collaborator lacked admin rights). Reviewed-PR-only is the process |

---

## 7. Mini glossary

| Term | Plain meaning |
|---|---|
| **Hypothesis (H)** | A testable guess about how a field is stored |
| **Checksum / CRC** | A number computed from data and stored beside it, to detect changes |
| **sum8 / sum16** | Add the bytes, keep the last 8 / 16 bits |
| **CRC-16/CCITT-FALSE** | A stronger, order-sensitive 16-bit fingerprint |
| **Resync** | Scan forward to the next place that fully validates as a record |
| **RDW / BDW** | Mainframe length headers: record descriptor word / block descriptor word |
| **RLE** | Run-length encoding: a compression that stores "this byte, repeated N times" |
| **XOR key** | A byte mixed into data to scramble it |
| **VLIR / SEQ** | Commodore file layouts (variable-length records / sequential) |
| **PETSCII** | The Commodore 64's character set |
| **DOS date** | A 16-bit packed date, with a separate packed time word |
| **Packed decimal** | Two digits per byte, with a sign nibble |
| **Calibration** | Converting raw instrument readings to real units |
| **Dropout** | A raw value that means "no reading" (LABLOG: -32768) |
| **False verified** | A record marked verified that is actually wrong. The worst kind of error for this tool |
| **Regression baseline** | Our own earlier output used as a reference. Not independent proof |
