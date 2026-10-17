# Issue 17: CVT selected-text budgets

CVT's optional large-input preflight replaces the coarse 2MiB refusal only after
checking its signature, complete directory/info blocks and established SEQ/VLIR
structure. The decoder and PETSCII semantics are unchanged. The public engine
retains the global 128MiB reader cap and the common selective 8MiB scan cap.

SEQ selects the physical bytes from offset 508 to the smaller of EOF and the
header's declared end. A zero declaration selects EOF, matching the decoder;
it cannot hide work. VLIR visits at most 127 slots and advances monotonically
by each slot's declared blocks. Each selected range is clamped to physical EOF.
Slots cannot alias earlier payloads and there is no compression.

Charge six work units and four Unicode output units per physically selected
byte. Reserve 1,536 output units for metadata and each VLIR record. The common
32MiB work / 16MiB output budgets are inclusive. SEQ text therefore fits at most
4,193,920 selected bytes under the output charge; other bounds can reduce that.
Malformed counts/last-byte values still receive existing decoder damage when
affordable. Input is not clipped. Refusal remains CVT/failed, no records, lossy
bad_length at offset zero. Direct internal decoder calls bypass public preflight.

Measurements (Python 3.12.15, Darwin arm64, one traced parsing+JSON run):

| Case | Input bytes | Coarse policy | Selective policy | Time ms | Peak traced bytes |
|---|---:|---|---|---:|---:|
| SEQ | 2,286,508 | refused | ok, 1 exact record | 164.191 | 23,911,992 |
| VLIR | 2,439,162 | refused | ok, 40 exact records | 181.489 | 7,327,671 |
| Output amplification, zero count | 4,318,508 | refused | refused before decoding | 0.392 | 66,398 |

See reports/issue-17-cvt-profile.json. Baseline measurements replay the original
435c07e coarse refusal with optional helpers disabled and the same unchanged
decoder; paired rows assert identical input hashes. Tracing excludes fixture
construction/input allocation, includes JSON serialization, and is not process
RSS. The larger SEQ trace includes the decoder's PETSCII join temporary; logical
output budgets are not an allocator promise or a portable timing guarantee.

Reproduce with the project Python:

```
python tests/test_cvt_large.py --profile-before
python tests/test_cvt_large.py --profile
python -m unittest discover -s tests -p test_cvt_large.py
```

The existing small-file policy is preserved. An absent/broken helper keeps coarse
refusal. The decoder still reports corrupt/truncated fields honestly; this is
selective bounded input support, not arbitrary large damaged-file streaming.
