# Issue 17: VAULT large-file budgets

This is the VAULT-only, M3 budget-owner slice of #17, claimed on branch
`issue-17-vault-budgets`. It changes the VAULT policy in `deadbits/_limits.py`,
its budget tests, and documentation. Other legacy formats retain their current
ceilings and need separate per-format PRs. This PR does not close #17.
The shared engine/CLI/model/helpers, the VAULT decoder and official fixtures are
unchanged. The public `salvage_bytes`/`salvage_file` pipeline still preflights
before invoking the decoder.

## Why these limits changed

Fixtures were created and profiled before changing the policy on baseline
`28d8b81`. A 2,881,456-byte valid binary archive and a 2,377,456-byte valid text
archive were refused by the coarse 2MiB ceiling. A 98,416-byte valid RLE archive
was refused because every stored byte was charged as 127 expanded bytes, even
though this particular RLE stream expands 1:1. No payload was corrupt.

The replacement does not raise the 16MiB work/output caps. It projects work more
accurately for the actual selected bytes, without allocating decoded payloads.
Plain binary retains a hash, not a copy of the payload in JSON. Text retains
Unicode output and needs additional passes. Compressed candidates can be counted
with a forward RLE90 grammar scan instead of pessimistically charging 127x for
all streams. The u16 declared decoded size is still never trusted as a bound.

## Exact accounting and remaining limits

- The global input reader limit remains **128MiB**, checked before file allocation
  and again while reading. Files are still read into memory; this is not a streaming
  file reader. The engine's >2MiB detection prefix remains 64KiB.
- Physical declared entries are `min(header_count, complete_index_entries)`.
  Each costs **1,536 projected output units**, including record/name allowance.
  The 16MiB output cap alone therefore permits at most **10,922 entries** before
  payloads. Missing or invalid indexes remain decoder-reported losses.
- Stored length is u16, including its four-byte BL header: each payload is at
  most **65,531 stored bytes**. Out-of-range/index-overlapping blocks or a
  mismatched BL/id are not expanded, matching the decoder's rejection rules.
- Every alias is charged again, because the decoder processes every reference.
  There is no unbounded cache or declaration-sized allocation.

Let `P` be an entry's stored payload length. Work charges are:

| Payload | Work units |
| --- | ---: |
| Plain binary/bitmap | `2 * P` |
| XOR binary/bitmap | `3 * P` |
| Plain text | `5 * P` |
| XOR text | `6 * P` |
| RLE only | `8 * sum(expanded_prefix_lengths) + 2 * P` |
| Both XOR/RLE flags | `8 * sum(expanded_prefix_lengths) + 4 * P` |

The eight-pass allowance conservatively covers RLE repeat temporaries, copies,
XOR, hashing, plausibility and UTF-8 failure/fallback work. Both candidate orders
are charged when both flags are set; the existing decoder's order and fallback
semantics are unchanged. Invalid streams charge the expanded prefix they could
allocate before failing. Calling an invalid stream zero work would allow a late
bad escape to hide amplification. The fixed stored-byte term covers projection
scans as well as transformation input work.

Retained output costs `1,536 * physical_entries + 4 * sum(text_expansion)`.
For text, the largest valid candidate size is reserved, even if `size` claims a
smaller value. Binary/bitmap payload bytes are not retained, so they add no text
charge. An invalid-only candidate can still consume work, but retains no text.

The work and output limits are each **16,777,216 units**, inclusive. These are
conservative logical byte-pass/Unicode/record projections, **not** process-RSS,
wall-time or exact serialized-JSON limits. JSON escaping and Python object
overhead differ. Input memory, record/damage objects, serialization and caller
allocations add to the footprint; a 16MiB projection is not a 16MiB RAM promise.
For example, plain binary references can total at most 8MiB of selected payload
under the work cap; plain text at most about 3.2MiB, with output/name overhead
potentially reducing that. This remains a selective policy, not general 128MiB
archive support.

Preflight uses constant additional state per entry and performs no decoded-output
allocation. Plain payload bytes are not scanned; their lengths are charged.
RLE scanning is linear in visited stored bytes. Cumulative budget exhaustion
stops before later aliases; it can inspect at most two extra 65,531-byte candidate
streams for the entry that triggers refusal. The index loop is separately bounded
by physical entries and the fixed output precheck. Direct calls to the internal
`formats.vault.decode` function do not replace the public engine preflight.

Budget refusal remains a recognized **VAULT / failed**, no recovered records,
lossy `bad_length` at byte zero, and an explanatory note. Corrupt-but-affordable
archives retain existing partial recovery and original offsets. No bytes are
silently clipped to make the input look complete.

Other legacy limits remain: 2MiB for LIBRA-98/LABLOG/WKS/CVT/EBCDIC-DUMP, plus
the existing structural projections of 200,000/400,000/500,000 bytes for
LABLOG/WKS/EBCDIC-DUMP. Archive/document adapters retain their own budgets.

## Measured results

Full measurements and identical input hashes are in
`reports/issue-17-vault-profile.json`. Python 3.12.14 on Windows; three runs per
case. Times are medians with `tracemalloc` enabled. Peak traced allocation covers
parsing, result conversion and JSON serialization; fixture construction and the
already allocated input bytes are excluded. It is not process RSS. Tracing adds
substantial Python-loop overhead, so these are reproducible observations, not
portable time guarantees or CI thresholds.

| Case | Input bytes | Before | After | After median ms | After traced peak bytes |
| --- | ---: | --- | --- | ---: | ---: |
| Valid binary | 2,881,456 | refused | ok, 48 records | 10.830 | 209,658 |
| Valid text | 2,377,456 | refused | ok, 48 records | 339.440 | 7,599,140 |
| Low-expansion RLE | 98,416 | refused | ok, 80 records | 287.390 | 61,514 |
| RLE aliases | 2,421 | refused | refused | 24.710 | 2,097 |
| XOR/RLE aliases | 2,421 | refused | refused | 61.990 | 2,053 |
| Invalid RLE after expanded prefix | 2,422 | refused | refused | 24.310 | 2,001 |
| Repeated plain payload | 92,020 | refused | refused | 2.030 | 1,943 |
| Record/output amplification | 320,020 | refused | refused | 0.250 | 1,878 |

Tests assert every legitimate record's independently chosen ID/name/size/hash
and text, unchanged deterministic JSON across executions, inclusive boundaries,
actual physical entry counts and refusal before any payload decoding. An
instrumented byte source proves an exhausted budget does not scan later aliases
or copy whole payloads. RLE vectors cover escaped literals, repeat counts 1/255,
dangling escapes, missing previous bytes and XOR position wrapping.

The prior generic-ceiling tests intentionally exclude VAULT now: they continue
protecting every format that still uses that policy. Dedicated exact-budget,
alias and amplification tests replace the VAULT coarse-ceiling assertion; the
safeguards are not deleted without replacement.

Reproduce:

```console
python -m unittest discover -s tests -p test_vault_large.py -v
python -m unittest discover -s tests -p test_limits.py -v
python tests/test_vault_large.py --profile
python -m unittest discover -s tests -p "test_*.py"
python tools/compare_expected.py
```
