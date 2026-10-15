# FORMAT-SPEC

Layouts reverse-engineered from the organizers' kit (30 samples + 7 reference outputs). Every field
is marked **confirmed** (matches a reference output and/or a checksum/size that validates on every
sample of that format) or **assumption** (consistent with the samples but not independently
verifiable). All integers little-endian unless stated. Source of truth: the bytes in
`samples/official/`; no third-party parser or specification was used or copied.

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

## PAK (s24) and WAD (s23) — game archives
PAK: `PACK`, dir_off u32, dir_len u32; 64-byte entries name[56] + offset u32 + size u32.
WAD: `IWAD`/`PWAD`, numlumps u32, dir_off u32; 16-byte entries offset u32, size u32, name[8]
(bytes after the first NUL are garbage and ignored). sha256 = SHA-256 of the extracted bytes.
No per-entry checksum exists, so in-bounds payload corruption is undetectable (stated limitation).
Confirmed: structure fully accounts for s23/s24 (directory ends exactly at EOF).

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

## WPD (s14-s15) — WordPerfect 5.x document
`FF 57 50 43`; doc area pointer u32 at 4; encryption key u16 at 0x0C (non-zero -> `unsupported` +
`encrypted`, no text); u16 at 0x22 = end of text (beyond EOF -> `truncated`, s15). Text: 0x0A ends a
paragraph, 0x0C page break, 0x0D soft return -> space, 0xC0-0xCF/0xD0-0xDF/0xE0-0xEF fixed-length
function codes skipped (`C3 0C C3` bold on, `C4 0C C4` off). **Assumptions (no reference output):**
0xA0 -> ordinary space, 0xA9 -> `-`, **0xAA is a soft hyphen and is dropped** (`co-operation`
becomes `cooperation`), paragraph/page_break record shape. The trailing summary strings after the
text pointer are ignored.

## BRAVO (s16-s17) — Xerox Alto editor
No magic. Text of CR-terminated paragraphs (empty paragraphs kept), then `0x1A`, then a binary
formatting trailer. **Assumptions:** paragraph boundaries = CR; trailer (format runs) is not decoded
and never raises damage because its structure could not be confirmed from two samples. Detection is
structural (printable prefix with CRs, one 0x1A, short trailer).

## Unknown / hostile input
Anything without a recognised structure -> `UNKNOWN` / `unrecognized` with size, first 64 bytes, strings
and entropy in `metadata`. Recognised-but-unreadable (e.g. `LB98` + 3 bytes, s29) -> `failed` + `truncated`.
