# Issue 17: WKS physical-stream budgets

The optional WKS helper permits a large file only when the owner's strict record
checker proves a contiguous stream with the established BOF and an exact EOF.
It never enters length repair or bytewise resynchronization. Fixed layouts,
variable label/formula lengths and worksheet coordinates are checked one record
at a time, with at most one u16-sized payload temporary. The M2 decoder and its
last-cell-write/value/verification semantics are unchanged.

Charge four work units per input byte. Reserve 4,096 output units, then charge
1,024 + four times payload bytes per physical cell assignment (even repeated
keys), 256 per column-width record and 512 per unknown-opcode damage entry.
Known overwritten scalar/window metadata does not accumulate output, but every
physical record counts toward the 100,000-item cap. Inclusive work/output caps
are 32MiB/16MiB, scan 8MiB, reader 128MiB. Unknown-opcode density is not a free
skip, and repeated large cell assignments cannot hide work behind last-write
semantics. All bounds use physical frames, not a worksheet's declared range.

Malformed framing, absent/extra EOF bytes and unknown large record shapes keep
the original coarse refusal. Budget refusal is WKS/failed with no records and a
lossy bad_length at zero. Small damaged-file recovery is unchanged. Output/work
charges are logical bounds, not process RSS or exact JSON lengths.

Python 3.12.15 / Darwin arm64, one traced parsing+JSON run:

| Case | Bytes | Before | After | ms | Peak traced bytes |
|---|---:|---|---|---:|---:|
| 36 exact 60,000-character labels | 2,160,406 | refused | ok, 36 cells | 6.476 | 6,505,375 |
| 18,000 metadata frames + one integer | 504,021 | refused | ok, exact A1=77 | 172.692 | 2,263 |
| Dense unknown opcodes | 440,010 | refused | refused before decoder | 132.906 | 2,347 |
| Label output pressure | 4,320,802 | refused | refused before decoder | 1.332 | 246,367 |
| Broken label boundary | 2,160,406 | refused | refused before decoder | 0.179 | 185,999 |

reports/issue-17-wks-profile.json pairs identical input hashes. Baseline profiles
replay the original coarse guard with helpers disabled and unchanged decoders.
Fixture/input allocation is excluded; parsing and JSON are traced. Timings are
single-machine observations, not cross-platform guarantees or process RSS.

Reproduce: python tests/test_wks_large.py --profile-before / --profile, and
python -m unittest discover -s tests -p test_wks_large.py. Tests check every
independently specified label/address, metadata/sparse output, deterministic
JSON, inclusive bounds, repeated assignments, early stop and refusal without
entering decoding/resync. No decoder, official fixture or issue-19 work changed.
