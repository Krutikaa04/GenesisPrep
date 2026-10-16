# Guided mentor demo

Issue #14 owns the new `deadbits/demo.py`, its orchestration tests, and this
document. The shared CLI parser remains M3-owned. Run the standalone module now;
`main(argv)` is available for the proposed `salvage --demo` delegation. This PR
does not add that switch to `deadbits/cli.py` or change recovery/validation formats.

```console
python -m deadbits.demo --kit-dir /path/to/organizer-kit --source-dir /path/to/source-checkout --output-dir /path/to/new-demo
python -m deadbits.demo --kit-dir /path/to/organizer-kit --output-dir /path/to/other-demo --guided
```

Both kit and output paths are explicit. The kit contains `samples/` and
`expected_outputs/`. Output must be a **new directory**, separate from the kit,
source checkout, and running application source tree, including resolved aliases.
Nothing is downloaded, installed, or edited in the source/official fixtures.
Only the output tree receives generated copies, recovery JSON and new evidence.

The default is noninteractive, including under redirection. `--guided` pauses
between steps only if both input and output are terminals. Redirected streams
automatically skip prompts; EOF switches to automatic continuation. The transcript
uses plain text and escapes terminal controls in fields/paths. Unsupported terminal
glyphs follow the existing presentation fallback.

## Walkthrough

1. **Normal recovery:** choose the first sorted, healthy version-2 LIBRA-98 sample
   with confirmed framing and at least one record. Copy it into the output tree
   and show actual recovered fields from the engine's saved JSON.
2. **Truncation:** cut a separate copy after the final record's flags and complete
   identity, before its remaining fields. Show recovered fields, emitted uncertainty,
   and actual damage kinds/byte offsets. The removed bytes are genuinely absent.
3. **Checksum damage:** XOR the first record checksum byte with 1 in another copy.
   Show unverified output and checksum damage. The whole-file checksum is not
   repaired: its additional mismatch is preserved as real collateral damage.
4. **Unknown input:** decode explicitly synthetic bytes `00 ff 00 ff`. Show the
   real UNKNOWN/unrecognized output without inventing records or accuracy.
5. **Validation summary:** use the existing reference, unittest and benchmark
   runners. Show counts, denominators, provenance and paths to their artifacts.
   Passing references/tests is never labelled general recovery accuracy.

Source selection is bounded to regular, nonsymlink LIBRA files at most 2 MiB;
the demo inspects only confirmed framing to choose mutation offsets. The engine
still performs all field decoding. This demo-specific cap does not change decoder
limits. If the kit lacks a suitable file, the first three steps are explicitly
unavailable; the synthetic unknown example and validation summary still run.
If engine behavior no longer exhibits a requested scenario, that step fails
instead of silently claiming a successful demonstration.

The preview shows the first two records and also the first unverified record
when needed. Damage output shows the first five entries. Complete records,
damage lists and metadata remain in the saved JSON. Verification markers are
exactly those emitted by the engine; structural consistency has documented limits.

Live source tests and benchmark scoring require an explicit trusted `--source-dir`.
Portable applications do not bundle these resources. Without it, those steps are
unavailable and explain the source-kit option; references can still run from the
explicit kit. A supplied source kit executes local tests/scoring code through
the existing runners. Normal recovery is always a new execution.
The current unittest module exposes `run_tests` rather than the dispatcher's
`run(request)` bridge; the demo calls that public API directly and saves the
schema envelope beside its artifacts. Reference and benchmark steps use the
existing validation dispatcher. No runner implementation is duplicated.

## Live, saved, and skipped proof

To present existing schema-1 proof instead of rerunning a selected validation step:

```console
python -m deadbits.demo --kit-dir /path/to/kit --output-dir /path/to/new-demo --historical-evidence test=/path/to/test-proof/validation.json --skip-validation benchmark
```

`--historical-evidence MODE=PATH` accepts `verify`, `test`, or `benchmark` once
each. Saved evidence is structurally checked by the existing loader and labelled
**historical**, retaining its recorded version, environment, time and commit.
Artifact paths resolve against the original evidence file, which stays untouched.
Artifact contents are not independently reverified. Missing proof/sections are
unavailable, malformed proof fails, and historical failures remain failures.
Historical proof never silently falls back to a live measurement.

`--skip-validation MODE` explicitly records a skipped step. It cannot combine
with historical proof for the same mode. Skipped/unavailable steps do not turn
into passes. New recoveries and any remaining live steps are separately labelled.

Exit 0 means every requested demonstration and validation step completed; exit 1
means a step failed or an operational error occurred; exit 2 is invalid CLI usage;
exit 3 means a step was skipped or unavailable. A benchmark marked `measured` can
complete with imperfect recovery: its actual scores remain visible. These demo
exits do not alter ordinary recovery's zero-exit contract.

## Saved bundle and callable boundary

The output tree contains:

- `inputs/`: generated copies, never mutations of the originals.
- `recovered/`: unchanged contract `<input name>.json` files and `report.json`,
  produced by the same recovery entry point as the CLI.
- `validation/<mode>/`: new runner artifacts and `validation.json` for live steps.
  Historical steps reference the existing evidence rather than copying it and
  breaking its relative artifact paths.
- `demo.json`: per-step states and live/historical labels, mutation parameters,
  original/input SHA-256 hashes, recovery/evidence paths, current demo version/time,
  and nested validation measurements with their own original contexts.
- `transcript.txt`: the plain UTF-8 walkthrough, saved independently of terminal
  encoding. Previews and paths can be followed back to real JSON/evidence.

`run_demo(kit_dir=..., output_dir=..., source_dir=None, historical=None,
skip_validation=(), guided=False, stream=None, input_stream=None)` returns the
manifest. The injectable streams support a future parser delegation and tests;
the function uses the real shared recovery and validation services. An operational
failure can leave partial artifacts; use a fresh directory for retry.

Tests use a tiny known-answer LIBRA fixture and a one-test source kit, rather
than recursively validating the entire development suite. They check actual
fields/damage, deterministic copies, unchanged source/fixture bytes, historical
metadata preservation, missing/failed/skipped steps, stream behavior and CLI use.
