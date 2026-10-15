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

### LABLOG (s05-s07)
* H1 `start` is unix time. **Failed**: gives 1972-10-11T05:07:43Z - right month/day/time, year 20 too low.
* H2 epoch 1990-01-01. **Confirmed**: `1992-10-11T05:07:43Z` (s05 expected).
* H3 interval = 50 ms literal. **Failed**: expected 500; field is in units of 10 ms.
* H4 channel table entry = unit[6]+f32+f32 (14 B). **Failed** (decoder error / wrong sizes): block length 24
  for 2 channels => 12 B per channel, unit is 4 bytes.
* H5 block CRC: tested sum/xor/CRC16 variants over several spans; CRC-16/CCITT-FALSE over `type..payload`
  matched 7/7; header CRC over bytes 0..29 matched.
* H6 only raw -32768 is a dropout. Confirmed by expected `-10091.5` (raw -20224 is a real value).

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
