# Issue 17: LABLOG retained-sample/event budgets

The optional large-input helper admits only complete CRC-valid headers/blocks
of established types 1/2/3, coherent physical lengths and a matching physical
block count. Channel count must be nonzero; samples require one preceding table
of exactly 12 bytes per channel with finite scale/offset values. Repeated tables,
unknown blocks, damaged checksums and ambiguous lengths retain coarse refusal.
This avoids large-file channel inference, overlapping CRC repair and historical
calibration walks. The M1 decoder and its CRC/recovery semantics are unchanged.

CRC validation uses stdlib binascii.crc_hqx with the same CCITT-FALSE parameters;
a separate known-answer vector establishes 123456789 -> 0x29B1. It scans views,
not copied payload aggregates. Every block is physically traversed; declarations
never size an allocation or determine iteration count.

Logical charges:

- Work: 8 * input bytes + 16 * physically framed sample/channel values.
- Output: 4096 + 64 * channels, plus 512 + 32 * channels per sample,
  plus 512 + 4 * message bytes per event.
- Items: physical blocks + samples + events. Every repetition is charged;
  repeated sample IDs/events are not collapsed to hide accumulation.

Inclusive bounds are 32MiB work, 16MiB output, 100,000 items, 8MiB selective scan
and the public 128MiB reader ceiling. Work alone caps this path at 4MiB; sample
values/output can reduce it substantially. Budget exhaustion stops before later
payload checks. Rejection stays LABLOG/failed, no records, lossy bad_length at
zero. Input is not clipped, and small damaged-input recovery is unchanged.

Python 3.12.15 / Darwin arm64, one traced parsing+JSON run per case:

| Case | Input bytes | Before | After | ms | Peak traced bytes |
|---|---:|---|---|---:|---:|
| 11,000 events + one calibrated sample | 2,310,061 | refused | ok, exact sample/events | 24050.289 | 10,167,553 |
| Dense 150,000 samples | 305,450 | refused | refused before decoder | 5.554 | 2,385 |
| 13,000 events, output pressure | 2,730,061 | refused | refused before decoder | 309.563 | 66,555 |
| Bad header CRC | 2,310,061 | refused | refused before decoder | 0.482 | 66,299 |
| Bad block CRC | 2,310,061 | refused | refused before decoder | 266.384 | 66,555 |

reports/issue-17-lablog-profile.json pairs identical input hashes. Baseline
profiles explicitly replay the original coarse refusal with helpers disabled and
unchanged decoders. Tracing excludes fixture/input allocation and includes JSON.
The valid run includes the unchanged pure-Python decoder CRC implementation;
tracing makes it substantially slower. These observations are not portable time
limits or process RSS. The new path improves admissible input, not CRC speed.

Run python tests/test_lablog_large.py --profile-before / --profile to reproduce,
or python -m unittest discover -s tests -p test_lablog_large.py. Tests assert
independent calibrated values, channel units, every event, deterministic JSON,
CRC vectors, inclusive budgets, physical counts and refusal without constructing
a full-file CRC index or entering length repair. No issue-19 work is included.
