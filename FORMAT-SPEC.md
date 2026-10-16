# FORMAT-SPEC

Layouts reverse-engineered from the organizers' kit (30 samples + 7 reference outputs). Every field
is marked **confirmed** (matches a reference output and/or a checksum/size that validates on every
sample of that format) or **assumption** (consistent with the samples but not independently
verifiable). All integers little-endian unless stated. Source of truth: the bytes in
`samples/official/`. M3 also checked WP5 framing facts against the original libwpd project
implementation during development; no third-party implementation code or dependency is bundled.

## Common behaviour
* Detection needs the format's own signature/structure; the file extension is never used.
* Decoders are record-by-record; a bad record is isolated and the scan resynchronises.
* Unreadable values are omitted or `null` and flagged (`verified:false`, `issues`); nothing is invented.
* Damage offsets are byte offsets into the input, clamped to the file size.
* Damage-kind rule when several apply: report the root cause (e.g. `truncated`, not also `count_mismatch`).

## LIBRA-98 (s01-s04, s29) — library circulation database
| Field | Layout | Status |
|---|---|---|
| magic | `LB98` | confirmed 4/4 |
| version / flags | u8 / u8; flags bit0 -> cp1252 (else cp437) | version confirmed (s01); flag bit0 confirmed (s03 `0x92`,`0xDF` decode only under cp1252) |
| count | u16 declared records | confirmed |
| created | DOS date u16 then DOS time u16 | confirmed (s01 expected `1998-10-03T11:20:22`) |
| data_offset | u16, records start there; bytes 16..data_offset hold a vendor string (s03) | confirmed |
| branch_id | u16 | confirmed |
| record | `A5` marker, len u8 (= flags..chk), flags u8, id u32, title pascal, author pascal, year u16 (+1500), price_cents u16, copies u8, isbn char[10], due_date DOS u16 (0 = none), chk u8 | confirmed on s01/s04 expected |
| record chk | sum8(flags .. byte before chk) | confirmed 22/22 records in s01-s03 |
| flags | bit0 checked_out (confirmed), bit1 deleted, bit2 reference_only | **bits 1-2 assumption** (field order in contract; plausible values on s02/s03) |
| trailer | `END!` + u16 = sum16 of every byte before `END!` | confirmed 3/3 |

Recovery: bad record checksum -> record kept `verified:false` + `checksum_mismatch`; wrong length byte ->
fields are self-delimiting, so the record is recovered if its checksum verifies (`bad_length`), otherwise
resync on the next valid record; truncation inside a record keeps only fully read fields (`id`).
`count_mismatch` only when the file is complete.


### M1 hardening decisions (2026-10-16)
* Length recovery also runs when the declared length goes past EOF. It requires
  self-consistent fields, a valid record checksum, an ISBN made of digits/`X`, and
  a valid due date. Otherwise the scan seeks a later validated record/trailer.
* Deleted/reference-only records remain present. Bits 1/2 remain an **assumption**
  (organizer question Q1 in PROJECT-HANDOFF.txt); this work does not confirm them.
* Truncated records intentionally expose only a fully read `id`, with
  `verified:false` and `issues:["truncated"]`. Other incomplete record fields are omitted.
* Duplicate IDs are all retained and marked unverified with `invalid_value`;
  uniqueness is an **assumption**, so duplicate damage is lossless.
* Version 2 is the only confirmed layout. Other versions attempt that layout,
  report `unknown_record`, and mark recovered records unverified (**assumption**).
  Version-2 extended headers use `data_offset`, not a fixed record start.
* Counts are compared only after a complete trailer; a partial `END!` marker or
  checksum reports truncation without a secondary count error. An out-of-file
  data offset is ambiguous (pointer corruption or an extended header cut short):
  report `oob_pointer`, recover from offset 16 if possible, and report a missing
  trailer as `truncated` rather than claiming a complete file.
* Resynchronisation also considers field-delimited checksum-valid records with
  a damaged length. A stray `END!` in garbage is skipped when a later validated
  record exists, while a checksum-valid real trailer still ends the record scan.
  Length recovery rejects undefined text bytes and impossible bodies above 255
  bytes instead of silently emitting replacement characters as verified text.
* A damaged file checksum does not invalidate independently checksummed records.
  Additive checksums are not collision-resistant; compensating byte changes,
  and the header's unprotected encoding flag, cannot prove original text identity.


### M1 reviewed refinements (2026-10-16)
* Record checksums establish raw bytes, not the header's code-page choice.
  This refines the earlier trailer-damage policy: ASCII remains independent,
  while codec-dependent non-ASCII titles/authors are unverified when trailer
  integrity is unavailable (`checksum_mismatch`, or `truncated` if incomplete).
  A damaged trailer alone is indistinguishable from a flipped encoding flag;
  the decoder never guesses an alternate codec to make the text look plausible.
* Version-2 in-bounds offset repair requires an earlier intact chain of exactly
  the declared count, a complete final trailer at EOF, and restoration of the
  stored file checksum by changing only the pointer bytes. At most 256 candidates
  are tested. More than one valid chain rejects repair. Raw metadata.data_offset
  is retained; the mismatch is lossless `invalid_value` at byte 12, alongside the
  actual file checksum damage. Vendor-header bytes are not blindly scanned.
* Recomputed trailers, compound checksum damage, appended bytes and competing
  record chains do not establish a unique earlier offset; they remain uncertain.
  An already intact, count-valid declared chain always wins over an alternative
  suggested by a trailer checksum error. Additive collisions cannot overturn
  intact framing evidence.
* Resynchronization carries its prefix checksum and parsed records advance it
  on non-overlapping memoryview ranges. Repeated local damage no longer sums
  the same file prefix repeatedly; additional checksum state is constant-size.
* A stray `END!` immediately before the real checksum-valid final trailer now
  reports the inserted gap and finishes at the real trailer. Partial records
  still expose only a complete ID; partial-field salvage is outside this pass.

## LABLOG (s05-s07) — instrument data logger
| Field | Layout | Status |
|---|---|---|
| header (32 B) | `LLOG`, version u8, nchan u8, interval u16 (x10 ms), instrument char[16], start u32, declared_blocks u16, header_crc u16 | confirmed |
| start | seconds since **1990-01-01** | confirmed s05 (`1992-10-11T05:07:43Z`); epoch is derived, not documented |
| header_crc | CRC-16/CCITT-FALSE over bytes 0..29 | confirmed 3/3 |
| block | `B1`, type u8, len u16, payload, crc u16 = CRC-16/CCITT-FALSE(type..payload) | confirmed 22/22 blocks |
| type 3 | channel table: unit char[4], scale f32, offset f32 per channel | confirmed (s05 expected) |
| type 1 | samples: first u16, n u8, n x nchan int16; value = raw*scale+offset; raw -32768 = dropout (null) | confirmed (s05 expected; dropout seen in s06) |
| type 2 | event: sample u16, severity u8, len u8, text | confirmed (s05 expected) |

A CRC-failed block still yields its samples as `verified:false` + `crc_mismatch` when its structure is
consistent; samples calibrated by a CRC-failed channel table, or timed from a CRC-failed header, are also
unverified. s07 contains one deliberately corrupted block.


### M1 hardening decisions (2026-10-16)
* A length-corrupted block resynchronises at a later complete CRC-valid block.
  Lost framing suppresses secondary count errors; later calibrated samples are
  unverified until a new intact channel table establishes calibration again.
* A CRC-failed but structurally coherent sample block is retained unverified.
  Failed header/table CRCs propagate to dependent records; events with a failed
  block/header CRC are explicitly unverified in metadata too.
* Truncated sample blocks are dropped in their entirety, including complete rows
  before the cut (**conservative recovery policy**): without the trailing CRC,
  genuine truncation cannot be distinguished from a corrupted block length.
  A partial block header is also `truncated`, without `count_mismatch`.
* Missing/malformed calibration emits `null` calibrated values and unverified
  records; raw ADC readings are never passed off as calibrated values. A
  malformed replacement clears the previous table. Non-finite calibration
  coefficients yield `null` for affected channels and `invalid_value`.
* Repeated channel tables report lossless `invalid_value`; the latest table
  applies to following samples (**assumption**, not organizer-confirmed).
  If units change, historical samples are unverified because the contract can
  expose only one channel-unit list for the file.
  No-channel headers fail with `invalid_value` rather than creating empty rows.
* Timing evidence: interval is multiplied by 10 (s05 reference proves the unit).
  All samples use `time_ms = sample * sample_interval_ms`; events carry sample
  indices, so their relative time uses the same multiplication. No new event
  time key is added. Using the s05-derived 1990 epoch gives s06
  `1993-09-01T20:06:50Z` (1000 ms interval) and s07
  `1994-04-02T21:02:06Z` (250 ms interval). These are **assumptions beyond s05**,
  checked against header bytes, not independent organizer goldens. No s06/s07
  reference output exists in this checkout; new golden assertions remain
  conditional on the organizers publishing those outputs.


### M1 reviewed refinements (2026-10-16)
* Before skipping a damaged length, the known table/sample/event schema supplies
  one candidate length. Repair is accepted only when restoring those two length
  bytes makes the original stored CRC match. A CRC-valid original always wins;
  missing CRCs, incomplete payloads and failed reconstructions remain damaged.
* If the header CRC fails, a unique channel width corroborated by independent
  CRC-valid table and sample blocks may replace the damaged count. Ambiguity is
  rejected. Header-derived uncertainty remains on all records/events via
  `header_checksum`; no metadata verification keys are introduced.
* A malformed replacement invalidates future calibration but retains the last
  usable channel-unit list. Historical unit provenance survives malformed tables,
  and incompatible later unit lists invalidate earlier samples only once each.
* Lookahead retains the next validated candidate or an exhausted-suffix flag.
  Repeated bad blocks no longer rescan the same remaining suffix; historical
  invalidation also advances monotonically. Magic alone is no longer sufficient
  recognition: coherent header or independent valid-block evidence is required.
* Truncated-row salvage remains outside this refinement: incomplete blocks are
  still dropped unless a complete payload and its original CRC prove a repair.


* Dense-marker stress tests also exposed overlapping CRC payload work and
  premature payload copies. A lazy, exact zero-initialized CRC prefix index
  now supports every block interval in at most 17 constant lookup steps, shared
  by lookahead, repairs and header-count inference. Logical prefix storage is
  2*(input size+1) bytes on supported runtimes; pristine sequential logs avoid
  allocating it. Candidate payloads remain memoryviews until block selection.
  This adds bounded linear index memory while removing repeated overlapping
  hashing and invalid-candidate payload copies. CRC semantics are unchanged.

## VAULT (s08-s10) — container of notes and scans
| Field | Layout | Status |
|---|---|---|
| header (16 B) | `VLT1`, count u16, xor_key u8, flags u8, index_off u32, names_off u32 | confirmed |
| header flags | bit0: name-length bytes are XORed with xor_key | confirmed on s09 (flags=1) vs s08/s10 (0) |
| block | `BL`, id u16, payload; from 0x10 | confirmed |
| index entry (16 B) | id u16, type u8 (1 text, 2 bitmap, 3 binary), flags u8 (bit0 RLE, bit1 XOR), name_off u32, block_off u32, stored_len u16 (incl. 4 B block header), size u16 | confirmed (size reproduced on 9/9 entries) |
| names | pascal strings at names_off; bytes XOR (key+i) | confirmed |
| payload | XOR (key+i) then RLE90 (`90 n` = repeat previous byte n times, `90 00` literal 0x90) | confirmed: decoded length equals index `size` on all entries |
| sha256 | of the decoded payload (bitmap: includes the 2 dimension bytes) | confirmed s08; bitmap hashing = assumption |
| text | UTF-8 (s09 contains non-ASCII) | confirmed |
| bitmap | first two decoded bytes are width, height | consistent with size = 2 + w*h on s09/s10 |

**Damage policy (M2, assumptions marked).** The index `size` is the only integrity check, so a record is `verified`
only when its block header matches the entry, the block is inside the file and outside the index table, the decoded
length equals `size`, the name is printable and (text entries) the text has no control characters other than
TAB/LF/CR. A length mismatch keeps the record but omits `sha256` (a hash of a payload of the wrong length cannot
match). `names_off` outside the file is one `oob_pointer`; the records keep their content with `name: null`. Index
lost (`index_off` outside the file) -> `failed` + `index_missing`, nothing salvaged: type, flags and names live only
in the index (assumption: unreferenced `BL` blocks are not scanned, a record built that way would be a guess).
Duplicate ids and unknown types are kept and flagged. **Stated limitation:** flips inside an uncompressed payload, or
a wrong `xor_key` that still produces printable text, cannot be detected - VAULT has no checksum.
Header flag bits other than bit0 are ignored (s09 has flags=1, nothing else seen); `xor_key` 0 is valid.

## WKS (s11-s13) — Lotus 1-2-3 worksheet
Record = opcode u16, length u16, payload. BOF 0x00 (0x0404), RANGE 0x06, COLW 0x08, BLANK 0x0C,
INTEGER 0x0D, NUMBER 0x0E, LABEL 0x0F, FORMULA 0x10, EOF 0x01; 0x02-0x05, 0x07, 0x0B are known
settings/named-range records that are skipped silently. Anything else -> `unknown_record` (s12: 0xFA).
Confirmed: all of the above on s11 expected. **Assumptions:** a cell written twice keeps its last value;
`number_format`/`iso_date` are emitted only for special (0x7x date/time) formats because the s11
reference carries none for currency cells; Lotus date serial 1 = 1900-01-01; serial 60 represents the non-existent 1900-02-29 due to the 1900 leap-year bug, so no ISO date is emitted for serial 60.

**Damage policy (M2).** The stream has no resync marker, so every record is checked against the layout. A known
opcode with a wrong length is repaired only when a strict chain of valid records follows at the known length
(`bad_length`, lossless; a cell is kept `verified:false`). Otherwise the decoder scans for the first offset where
>= 3 consecutive strictly valid records (or a chain ending in EOF at end of file) begin; skipped bytes are lossy
`unparsed_bytes`. If none exists: `truncated` (record runs past EOF) or the remainder is unparsed. Known payload
lengths (assumption, all kit files agree): BOF 2, RANGE 8, COLW 3, settings 02-05 1, WINDOW1 (07) 31, named range
(0B) 24. A record at an odd length is accepted only when the declared end is itself followed by a coherent chain.
Cells outside the declared range are kept without damage; RANGE is metadata only. **Known limit (organizer question
Q5):** a cell overwritten by a corrupted row/col byte is indistinguishable from a deliberate double write; the last
write wins and nothing is reported. i16 INTEGER cells cannot hold date serials > 32767 (those need NUMBER); a
negative i16 never produces `iso_date`. Serial 60 (phantom 1900-02-29) yields no `iso_date`.
Format nibble: only date/time (0x71-0x79) emit `number_format` (kept from s11).

## EBCDIC-DUMP (s20-s22) — mainframe tape extract
cp037; records are RDW (u16 BE length incl. the 4 header bytes + u16 zero); s21 wraps records in VB
blocks (BDW u16 BE + u16 zero). `H` title char[20] + run date char[8]; `D` student_id char[6], name
char[20], dob packed(5) = 0YYYYMMDD+F, gpa packed(3)/100, credits u16 BE, status char, balance
packed(4)/100 (sign nibble D/B = negative), 2 filler; `T` count packed(4), credits total packed(5).
Confirmed on s20 expected; trailer totals reconcile on s20/s21 (402, 546).


### M1 hardening decisions (2026-10-16)
* RDWs and BDWs are bounded by the file and enclosing block. Invalid RDW
  lengths/reserved bytes seek a later complete, schema-consistent known record;
  a corrupted block descriptor seeks the next credible BDW and marks records
  recovered under the damaged descriptor unverified. Known header/data/trailer
  payload sizes are 29/44/10 bytes, excluding the four-byte RDW.
* A next block's first RDW may itself be damaged: its known payload schema can
  still establish that BDW boundary. A record never consumes bytes across an
  established block boundary. This recovery policy is an **assumption** based on
  the sample generator's fixed schemas, not a general-purpose mainframe parser.
* Framing loss/truncation suppresses derivative trailer count/credits errors.
  Missing trailers report truncation; incomplete records are dropped rather than
  inventing partial student fields. Outer-block and inner-record truncation from
  the same EOF cut produce one root damage report.
* Empty/invalid packed fields return unavailable values; invalid dates, digit or
  sign nibbles flag records. Packed signs B/D are negative, A/C/E/F positive.
  Invalid trailer totals are `invalid_value`, not usable reconciliation evidence.
* A credits-total disagreement cannot identify whether a record or trailer is
  wrong: keep every recovered record but mark them unverified with
  `checksum_mismatch`. This total is not a checksum over the other record fields.
* Detection needs a credible cp037 header/date, or a sufficiently long printable
  prefix of a truncated known-length header. A lone `H` byte after zeros is
  insufficient. Descriptor corruption alone need not erase header recognition.
* RECFM F support was assessed and is intentionally not inferred: no F sample,
  reference, LRECL, or padding convention is supplied. Removing RDWs creates
  variable-sized H/D/T payloads, which is not evidence of a fixed-length format.
  Such files remain unrecognized; no speculative adapter path is added.
* There is no per-record integrity checksum. Plausible changes to names, IDs,
  dates, GPA, status or balance can pass structural validation undetected.


### M1 reviewed refinements (2026-10-16)
* VB boundary evidence now uses known RDW framing independently of the first
  student's semantic field validity. A damaged first RDW may be bounded by its
  fixed schema and an intact following RDW; the damaged record is still dropped,
  while its intact sibling remains recoverable. An intact RDW length plus a
  coherent following sibling also preserves the boundary if the first record's
  type byte is unknown or inconsistent. No partial-field salvage is added.
* A damaged header date/title can still identify the format when the header
  descriptor and two credible student records independently establish framing.
  Detection inspects at most eight records. With fewer independent records,
  damaged-header files may deliberately remain unrecognized.
* Printable cp037 accents are valid text; control-corrupt title, name or status
  fields become null with `invalid_value`. Affected students are unverified.
  No undocumented GPA/status domain restrictions are introduced.
* Resynchronization filters fixed schema lengths before slicing payloads, so
  hostile large descriptors cannot repeatedly copy large payload suffixes.

## PAK (s24) and WAD (s23) — game archives
PAK: `PACK`, dir_off u32, dir_len u32; 64-byte entries name[56] + offset u32 + size u32.
WAD: `IWAD`/`PWAD`, numlumps u32, dir_off u32; 16-byte entries offset u32, size u32, name[8]
(bytes after the first NUL are garbage and ignored). sha256 = SHA-256 of the extracted bytes.
No per-entry checksum exists, so in-bounds payload corruption is undetectable (stated limitation).
Confirmed: structure fully accounts for s23/s24 (directory ends exactly at EOF).

### M3 archive hardening (2026-10-16)
* Decode at most 100,000 physically complete entries. Declared counts stay in
  metadata; excluded entries produce lossy `bad_length`, never an `ok` result.
* Payloads must fit outside the header/directory. Invalid entries retain raw
  directory facts, omit SHA-256, and carry `verified:false` / `oob_pointer`.
* Duplicate names and overlapping nonempty ranges are retained and marked
  unverified with lossless `invalid_value`. **Policy assumption:** either may
  be intentional, but the intended identity/range cannot be established.
* Zero-byte markers hash empty bytes without dereferencing their raw pointer
  (**policy assumption** for PAK as well as WAD). Adjacent ranges do not overlap.
* Hashing uses memoryviews and exact-range caching. Unique hashes consume at
  most 4 times the input size; budget-excluded hashes are omitted and flagged
  with lossy `bad_length`. Alias reuse remains available after exhaustion.
* Duplicate lookup is linear; a sorted interval sweep reports one warning per
  connected overlap component in O(n log n), rather than every overlapping pair.
* Only PACK/IWAD/PWAD are supported. Bare magic is insufficient; damaged count
  or directory length needs independent credible entry evidence among at most
  eight entries. Complete directory loss prevents evidence-based recovery.
* Empty/control-containing names are retained unverified. Bytes after a name's
  first NUL remain ignored. A calculated hash proves selected bytes, not their
  identity before corruption; these formats contain no integrity checksum.

## CVT (s18-s19) — Commodore 64 GEOS convert
254-byte blocks. Block 0: type, name char[16] PETSCII (0xA0 padded) at 3, structure u8 at 0x15
(0 seq, 1 vlir), geos_type at 0x16, date year-1900/month/day/hour/minute at 0x17, declared_blocks u16
at 0x1C, signature `PRG formatted GEOS file V1.0` at 0x1E. Block 1: class_name char[20], author
char[20], description. SEQ: data blocks follow. VLIR: block 2 = 127 x (blocks u8, bytes-in-last-block u8),
`(0,0xFF)` = no record; slots keep their index. PETSCII: 0x41-0x5A lower case, 0xC1-0xDA upper case,
0x0D newline. Confirmed on s18 expected; VLIR layout confirmed by s19 structure (slots 0, 2, 3; sizes
20/254/300) but there is no reference output for it.

**Damage policy (M2).** For VLIR the record index and the file size are independent evidence of the block count:
index total == file size != `declared_blocks` -> the header field is corrupt, records stay verified, lossless
`count_mismatch`; index disagrees with both -> every record `verified:false` + `count_mismatch` (lossy). A slot with
0 blocks but a byte count other than 0 / 0xFF is `invalid_value` (later records would be mis-sliced). **Assumption
(s19 only):** the last block of a VLIR record is NUL padded - non-NUL bytes after the declared byte count, or a
count that ends inside padding, make the record `verified:false` + `bad_length`. SEQ bytes beyond
`declared_blocks` x 254 are dropped, reported as lossy `unparsed_bytes`, record unverified. PETSCII bytes without a
text equivalent (graphics, `\`, `^`, `_`) become U+FFFD and the record is `verified:false` + `invalid_value`; they are
never mapped to a guessed character. The VLIR structure has no reference output (s19 only): slot semantics, `(0,0)`
and `(0,0xFF)` as unused, and the count of blocks after block 0 are assumptions confirmed only by s19's internal
consistency.

## WPD (s14-s15) — WordPerfect document profile
The kit has `FF 57 50 43`, product 1, file type 10, version 2.0, a document
pointer u32 at 4, and a kit-specific text-end u16 at 0x22. Encryption key u16
at 0x0C nonzero means `unsupported` + `encrypted`, with no text emitted.
The text stream uses WP5-style function gates although the version byte is
associated with WP6 elsewhere. **Scope assumption:** only this kit-backed
header/text profile is decoded; other product/type/version combinations are
recognized conservatively and reported `unsupported` / `unknown_record`.

WP5 framing facts were checked against original [libwpd fixed-group source](https://sourceforge.net/p/libwpd/code/ci/master/tree/src/lib/WP5FixedLengthGroup.cpp)
and [variable-group source](https://sourceforge.net/p/libwpd/code/ci/master/tree/src/lib/WP5VariableLengthGroup.cpp):
* C0-CF total widths: 4,9,11,3,3,5,6,7,4,5,6,6,8,10,10,12.
* D0-FF framing: gate, subgroup, u16 size, payload(size-4), u16 size,
  subgroup, gate. Total width is size+4, minimum size 4. Mirrored size,
  subgroup and closing gate must agree inside the declared text region.
* Only C3/C4 formatting gates occur in the kit. Other function layouts are
  independent implementation evidence, not organizer-confirmed coverage.
  Delimiting a group does not establish its text semantics: unimplemented
  groups are skipped with lossy `unknown_record` and the affected paragraph
  is unverified. C0 extended characters use U+FFFD rather than invented tables.
* Ambiguous function framing stops recovery at that boundary. Independent
  earlier paragraphs remain; an incomplete text prefix is unverified, and
  payload bytes cannot leak into apparently verified paragraphs.
* Hard LF ends a paragraph; FF emits a page-break record. Text on later pages,
  empty hard-return paragraphs and tabs are preserved. Soft page/return map
  to space. **Retained kit assumptions:** A0 ordinary space, A9 hyphen,
  AA dropped discretionary hyphen. Unknown bytes become U+FFFD and are flagged.
* A text-end past EOF produces truncation (s15); trailing summary bytes never
  complete a cut function. At most 8MiB of text and 100,000 records are decoded;
  budget loss is explicitly partial + lossy `bad_length`.
No organizer WPD reference exists: s14/s15 text checks are regression evidence.

## BRAVO (s16-s17) — Xerox Alto editor
There is no magic. CR-delimited paragraphs, including empty paragraphs, precede
0x1A and a binary trailer (15 bytes in s16, 17 in s17).
**Sample-based recognition assumptions:** at least 8 bytes of CR-terminated
printable ASCII text (TAB/LF allowed), one delimiter, then a 4..512-byte trailer
with at least two NULs and a non-whitespace control byte. Plain DOS EOF text,
textual/NUL-only trailers, short prefixes and multiple delimiters are rejected.

Missing-marker/high-byte text cannot be safely auto-identified. When identity
is independently known, direct decoding preserves CR paragraphs, marks an
unterminated final paragraph unverified, reports a missing marker as truncated,
and replaces unsupported bytes with U+FFFD + `invalid_value`. Independent
paragraphs stay intact. Recognition/text scans are capped at 8MiB; decoding also
caps records at 100,000. Exhaustion retains prior records with explicit lossy
`bad_length`; a cut current prefix remains unverified.

**Unproved bonus:** no consistent start/length/font/look layout was established
for both trailers. `metadata.format_runs` remains absent, and direct text
recovery does not pretend to validate that uninterpreted trailer.

## Unknown / hostile input
Anything without a recognised structure -> `UNKNOWN` / `unrecognized` with size, first 64 bytes, strings
and entropy in `metadata`. Recognised-but-unreadable (e.g. `LB98` + 3 bytes, s29) -> `failed` + `truncated`.

### M3 platform safety policy (2026-10-16)
* Public modules in `deadbits/formats/` with a contract-approved NAME and callable
  detect/decode register automatically in sorted order. Private helper modules
  and the template are ignored. Broken imports/detectors do not mask siblings;
  invalid result shapes/identity become a failed file, not invalid JSON.
* File reads are capped at 128MiB before allocation and bounded again while
  reading to handle growth. Symlinks, FIFOs and other nonregular files are
  reported failed without following/blocking. Inode/device checks reject a
  replaced input; O_NOFOLLOW/O_NONBLOCK are used where available.
* Large legacy detection (>2MiB) sees only a 64KiB prefix, so a corrupt LABLOG
  header cannot allocate a full-file CRC index before resource refusal. This
  may deliberately leave an oversized damaged file UNKNOWN when the prefix
  cannot independently identify it. Recognized budget refusals are failed
  with lossy `bad_length`; no missing bytes are invented as records.
* M1/M2 adapters have a conservative 2MiB decode ceiling. Structural-item
  projections additionally cap LABLOG at 200,000 bytes, WKS at 400,000 bytes,
  EBCDIC-DUMP at 500,000 bytes. These are safety policies (100,000 minimum-size
  items), not on-disk format limits. They can refuse a valid sparse file.
* VAULT independently limits projected work/output to 16MiB each. It charges
  every physical declared index reference, including aliases, using a 127x RLE
  expansion upper bound, both candidate orders, Unicode text width and fixed
  record/name overhead. Declared decoded size cannot reduce the budget.
* UNKNOWN metadata scans only the first 1MiB, reports analysis_prefix_bytes
  when sampled, and caps strings at ten of at most 256 characters each.
* UTF-8/LF JSON escapes undecodable filename bytes losslessly and rejects
  non-finite numbers. Atomic replacement protects existing output symlink
  targets; one file's write failure does not stop independent siblings.
* Input/output directories must differ to avoid overwriting source files.
  Exact per-file names are kept. A basename already at the filesystem name
  limit may make its `.json` suffix impossible; basename `report` conflicts
  with the mandated combined `report.json`. Those cases are explicitly failed
  in the combined report, whose three top-level keys are preserved. They
  cannot receive both mandated documents on that filesystem/contract.
* Existing optional report-row notes carry operational failures. Whether
  organizers allow extra row keys remains Q2 in PROJECT-HANDOFF.txt; the
  per-file six-key contract and all status/damage vocabularies are unchanged.
