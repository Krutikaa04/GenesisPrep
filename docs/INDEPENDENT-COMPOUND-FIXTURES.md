# Issue 16: independent known answers and compound damage

Claim: branch `issue-16-independent-fixtures`, M1 subset LIBRA-98/LABLOG/EBCDIC-DUMP
and M2 subset VAULT/WKS/CVT, recorded on
[issue #16](https://github.com/Krutikaa04/GossipGurls_Genesis_PS2/issues/16#issuecomment-6221270507).
Changes are confined to a new test module and this document. No decoder, shared
engine/model/CLI/helper, existing format test, or official fixture is edited.

`tests/test_fmt_compound_known_answers.py` builds 29 deterministic cases using
existing independent test fixture writers. Expected fields are chosen in the test
before packing: struct for descriptors, stdlib codecs for character sets, a
separate bitwise CRC implementation for LABLOG, and SHA-256 over known VAULT
payload bytes. No pristine decoder output is used as truth. The new module does
not read organizer inputs or outputs. These are independent synthetic answers,
separate from both the seven organizer comparisons and decoder-derived regression
equality in the general benchmark.

## Matrix

| Owned format | Cases | New controls and compound scenarios |
| --- | ---: | --- |
| LIBRA-98 | 5 | Pristine; duplicate IDs plus record/file checksum damage; encoding-flag change plus truncation; bad record length plus bad record checksum with an intact later record; near-magic negative |
| LABLOG | 4 | Pristine calibration/dropout/event metadata; header CRC plus sample CRC damage plus truncated event; oversized sample length plus truncated event; plausible magic without credible header |
| EBCDIC-DUMP | 5 | Pristine VB records and metadata; invalid packed DOB plus credits/trailer disagreement; damaged RDW plus cut sibling; invalid header date with independent student evidence; same bad header with insufficient evidence |
| VAULT | 5 | Pristine compressed/XOR text and binary; bad block pointer plus partial index; duplicate IDs plus invalid UTF-8; bad names pointer and decoded size plus partial index; near-magic negative |
| WKS | 4 | Pristine cells and metadata; duplicate cell plus repaired numeric length plus cut EOF; uncertain label encoding plus malformed formula terminator plus missing EOF; near-BOF negative |
| CVT | 6 | Pristine SEQ and sparse VLIR; bad last-byte count plus truncated record; impossible empty index slot plus PETSCII graphics; header/index disagreement plus truncation; near-signature negative |

For every case the oracle checks:

- Contract-valid, JSON-serializable output, bounded damage offsets, and no caught
  decoder exception.
- Exact expected format, status, ordered records and payload fields. Extra fields,
  missing fields and extra/missing/duplicate records cannot silently pass. Lists
  preserve duplicate identities rather than collapsing them into dictionaries.
- Required damage kinds and selected independently known metadata.
- Explicit uncertainty on affected output positions. A record left verified must
  equal a **complete** independently chosen truth record, including all fields.

Only `verified` and `issues` are excluded from payload-field equality, then checked
separately. Damage-kind assertions require known root kinds; additional honest
collateral damage is allowed. The matrix does not prescribe incidental diagnostic
wording or require the same offset for every manifestation of a compound fault.

## Assumptions and limits

These fixtures retain existing format policies from `FORMAT-SPEC.md`; they do not
claim new facts about unknown generators:

- LIBRA flag bits 1/2 remain assumptions. Duplicate records are retained and marked
  uncertain. A changed unprotected codec flag plus missing trailer cannot prove the
  original non-ASCII text: the fixture independently specifies the alternate cp1252
  rendering (`Caf\u201a`, `Zo\u2030`) and requires uncertainty. That rendering is not
  treated as original truth. Length repair cannot authenticate a second checksum
  fault; a damaged victim may be lost while later intact records remain recoverable.
- LABLOG CRC repair and scaling use only supported framing/calibration. Header or
  block CRC damage must keep derived samples unverified. A cut event cannot be
  reconstructed from its prefix.
- EBCDIC framing uses the documented fixed schemas and cp037. A malformed packed
  date becomes null. A credits-total disagreement cannot identify which side is
  wrong, so all affected students remain unverified. A damaged header without enough
  independently credible records stays unknown rather than guessing recognition.
- VAULT has no payload checksum. Its computed hash describes the selected bytes;
  it does not prove original content. Wrong decoded size suppresses the hash;
  out-of-bounds blocks cannot invent text/hash fields. Invalid UTF-8 is displayed
  through the existing cp437 fallback, always unverified. Duplicate IDs retain the
  current ambiguity policy. Plausible same-length corruption remains a documented
  limitation; this finite matrix does not imply it is detectable.
- WKS keeps the last complete write to a cell (existing assumption). Repaired cell
  lengths, non-ASCII label encoding and broken formula tokens remain unverified.
  A malformed duplicate is not grounds to invent another cell or merge two values.
- CVT VLIR interpretation and NUL-padding rules remain assumptions beyond the SEQ
  reference. Index ambiguity propagates uncertainty; truncated text may expose only
  the bytes present. PETSCII graphics with no established text mapping use U+FFFD
  and cannot remain verified.

## Measurements

Baseline application commit: `4befda0` (merged PR #28). The new matrix was first
executed against that commit's unchanged decoders. It passed all 29 cases before
any runtime edits; no decoder correction was necessary. The final run uses the
same decoder code, so there is no claimed recovery-score improvement.

| Check | Before | After |
| --- | ---: | ---: |
| Full unittest discovery | 489 tests, 12 skipped | 495 tests, 12 skipped |
| Organizer reference agreement | 7/7 | 7/7 |
| Independent issue-16 matrix | 29/29, baseline decoders | 29/29, unchanged decoders |
| New suite methods enforcing that matrix | 0 | 6, covering 29 subcases |
| Incorrect verified records in the matrix | 0 | 0 |

Final observed outputs, with exact field assertions satisfied:

| Format | Emitted records | Asserted fields | Verified | Unverified |
| --- | ---: | ---: | ---: | ---: |
| LIBRA-98 | 8 | 78 | 4 | 4 |
| LABLOG | 9 | 27 | 6 | 3 |
| EBCDIC-DUMP | 10 | 70 | 6 | 4 |
| VAULT | 6 | 37 | 2 | 4 |
| WKS | 15 | 78 | 12 | 3 |
| CVT | 9 | 18 | 3 | 6 |
| Total | 57 | 308 | 33 | 24 |

Cases and unittest methods are different counts: each format method has named
subtests. Field counts count emitted payload fields whose exact values/key sets
were asserted; they are not all bytes lost/recovered. The 33 verified records each
matched a complete independent truth record; all required uncertainty checks
passed. These finite observations do not predict hidden scores or guarantee
correctness under other compound changes.

Reproduce the matrix and its deterministic per-case input hashes:

```console
python -m unittest discover -s tests -p test_fmt_compound_known_answers.py -v
python tests/test_fmt_compound_known_answers.py --measure
python -m unittest discover -s tests -p "test_*.py"
python tools/compare_expected.py
```

The diagnostic `--measure` report records every failed case instead of hiding it;
the unittest command is the pass/fail gate. No production benchmark scoring code
is replaced. Reports can be saved outside the source/official trees with ordinary
shell redirection.
