# Issue 17: LIBRA complete-chain budgets

LIBRA's optional large-input path admits only version-2 files with a physical
END! trailer, an in-bounds u16 data pointer, a complete chain of record markers
and lengths, matching physical/header counts, and individually valid fields and
record checksums. The existing owner parser checks one <=255-byte record at a
time; no aggregate is retained by preflight. This also proves the decoder's
_valid_chain check succeeds, avoiding its damaged-pointer candidate search.
The LIBRA decoder and its recovery/verification semantics are unchanged.

Reserve 1,536 output units, then charge 1,024 fixed units plus four times body
length per physical record. Charge eight work units per input byte. Inclusive
limits are 32MiB work, 16MiB output, 100,000 items and 8MiB selective scan; the
public reader still caps at 128MiB. Work alone caps this path at 4MiB. Output
further limits it, e.g. at most 8,207 maximum-width 255-byte bodies. Header counts
never create iterations or allocation. Budget exhaustion stops before parsing
later records. These are logical byte/record bounds, not process-RSS promises.

Malformed lengths, bad record checksums, uncertain fields, count disagreement,
other versions and ambiguous pointer chains keep the original coarse refusal.
The helper does not attempt large-file resynchronization. Affordable small
corrupt files keep their existing recovery. A budget refusal is LIBRA-98/failed,
no records, lossy bad_length at zero; bytes are never silently clipped.

Measured Python 3.12.15 / Darwin arm64, one traced parsing+JSON run per case:

| Case | Bytes | Before | After | ms | Peak traced bytes |
|---|---:|---|---|---:|---:|
| 8,200 exact long-title records | 2,107,422 | refused | ok, 8,200 records | 955.302 | 13,979,482 |
| 8,210 records, output pressure | 2,109,992 | refused | refused before decoder | 312.776 | 68,539 |
| Count changed to 65,535 | 2,107,422 | refused | refused before decoder | 309.322 | 68,539 |
| First length changed to zero | 2,107,422 | refused | refused before decoder | 0.111 | 66,213 |

reports/issue-17-libra-profile.json pairs identical input hashes. Baseline
measurements replay the original coarse guard with optional helpers disabled
and unchanged decoders. Fixture/input allocation is excluded; parsing and JSON
serialization are traced. These are not RSS or portable timing guarantees.

Reproduce with python tests/test_libra_large.py --profile-before / --profile,
and python -m unittest discover -s tests -p test_libra_large.py. Tests compare
all independently specified fields, deterministic JSON, inclusive output/work/
item boundaries, early stop and refusal before recovery decoding. No M1 decoder,
official fixture, recovery contract or issue-19 behavior is changed.
