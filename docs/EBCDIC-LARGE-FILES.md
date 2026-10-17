# Issue 17: EBCDIC physical-descriptor budgets

The optional platform helper admits coherent V/VB extracts with the established
fixed H/D/T record shapes. Each RDW must fit its physical region; each VB BDW
must have zero reserved bytes and fit the input. The owner's existing layout
and record-boundary checks prove framing before decoding. No resynchronization
search is needed. The M1 decoder and field verification semantics are unchanged.

Charge eight work units per input byte. Reserve 4,096 output units, then charge
1,024 per physical student record and 64 per header/trailer, including repeats.
Every RDW and every VB BDW counts toward the 100,000-item cap. Inclusive limits
are 32MiB work, 16MiB output, 8MiB scan and the existing 128MiB reader ceiling.
Thus the work budget additionally limits this path to 4MiB. Declared trailer
counts never determine allocation or iteration. Repeated metadata costs work
and items even though its decoded values overwrite earlier metadata.

Unknown record shapes, invalid descriptors and incoherent large framing keep
the original coarse refusal. Refusal remains EBCDIC-DUMP/failed with no records
and a lossy bad_length at zero. Small damaged-file recovery is unchanged.
Logical charges are not process RSS or exact serialized JSON size guarantees.

Python 3.12.15 / Darwin arm64, one traced parsing+JSON run:

| Case | Bytes | Before | After | ms | Peak traced bytes |
|---|---:|---|---|---:|---:|
| V, independently specified students | 576,047 | refused | ok, 12,000 students | 810.629 | 8,948,080 |
| VB, same students | 576,099 | refused | ok, 12,000 students | 815.129 | 8,941,091 |
| 65,000 headers + one student | 2,145,062 | refused | ok, exact student | 2,264.408 | 67,819 |
| Student output pressure | 816,047 | refused | refused before decoder | 112.257 | 2,242 |
| Dense unknown RDWs | 550,033 | refused | refused before decoder | 0.155 | 2,200 |
| Invalid BDW reserved byte | 576,099 | refused | refused before decoder | 0.188 | 2,181 |

reports/issue-17-ebcdic-profile.json pairs identical input hashes. Baseline
profiles replay the original coarse guard with helpers disabled and unchanged
decoders. Fixture/input construction is excluded; parsing and JSON are traced.
These observations are not cross-platform timing guarantees or process RSS.

Reproduce: python tests/test_ebcdic_large.py --profile-before / --profile, and
python -m unittest discover -s tests -p test_ebcdic_large.py. Tests assert every
independently specified student field, V/VB equivalence, deterministic output,
metadata-heavy input, inclusive budgets and early refusal before decoding or
resynchronization. The shared dispatcher also rejects an empty-string helper
result, preserving refusal unless a helper explicitly returns None.

No decoder, official fixture or issue-19 work changed.
