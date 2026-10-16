# CLI diagnostics and validation modes

Issue #13 preserves `salvage <input_dir> <output_dir>` and all mandated recovery
JSON. Recovery still returns exit 0, including usage and operational failures.
Its terminal summary reports file statuses, record counts and damage counts;
these are not accuracy percentages. `--verbose` adds per-file counts.
Use `--` before folder names that start with a dash.

The new modes use these exit codes, established before implementation:

| Exit | Meaning |
| --- | --- |
| 0 | Doctor checks available, or requested validation complete |
| 1 | Failed validation, malformed evidence, runner error or operational error |
| 2 | Invalid diagnostic/validation invocation |
| 3 | Required runner/resource/measurement unavailable |

`--help` and `--version` exit 0. Legacy recovery usage errors retain exit 0;
usage errors requesting `--doctor`, `--verify`, `--test` or `--benchmark` exit 2.
Only one mode can be selected. Output uses plain text, no ANSI or interactive
prompts, including when redirected. Unsupported terminal filename glyphs are
escaped, and controls in data are escaped.

```sh
salvage --doctor
salvage --doctor --source-dir "/path/to/source kit" --kit-dir "/path/to/organizer kit"
salvage --verify --kit-dir "/path/to/organizer kit" --evidence-dir /tmp/reference-proof
salvage --test --source-dir "/path/to/source kit" --evidence-dir /tmp/test-proof --verbose
salvage --benchmark --kit-dir "/path/to/organizer kit" --corpus-dir /tmp/variants --evidence-dir /tmp/benchmark-proof
salvage --verify --evidence-file /tmp/reference-proof/validation.json --verbose
```

Doctor reports interpreter/version, all ten adapters, runner availability and
local source/kit presence. It does not run tests, verify kit contents, install
software or download anything. Source paths are auto-detected only for a source
layout containing tests and tools; installed/portable applications may need
explicit external paths. `--kit-dir` contains `samples/` and `expected_outputs/`;
`--samples-dir` and `--expected-dir` override these separately.

`--evidence-file` presents a saved schema-1 envelope, limited to 8 MiB, and
selects only the requested reference, test or benchmark section. It always
marks that section historical, retaining recorded version/environment/time.
Relative artifact paths resolve against the evidence file's directory. This
structural load does not verify artifacts or prove the truth of old evidence.
It cannot combine with live resource/output options and never executes files.
Missing sections are unavailable, never a successful empty run.

Live execution needs a **new** `--evidence-dir`, outside the source, samples,
references and corpus trees (including resolved aliases). Existing directories
are refused so validation cannot overwrite recovery `report.json`, source or
previous evidence. Runners save actual outputs, differences, logs and ledgers
there; `validation.json` is reserved for the CLI envelope. Failed runs may leave
partial artifacts; use a fresh directory for retry. Evidence paths are not
commands and are never shell-expanded.

## Integration boundary for issues #10, #11 and #12

Those runner implementations are separate issues and are not bundled by #13.
Until installed, live modes return 3 and name their missing prerequisite;
no output directories are created and no passing measurements are fabricated.
Existing source tools remain available meanwhile:
`python tools/compare_expected.py`, unittest discovery and `tools/evaluate.py`.

Runner authors expose `run(request) -> ValidationEvidence` in:

| Mode | Module | Required evidence |
| --- | --- | --- |
| `--verify` | `deadbits.validation.reference` | `reference` |
| `--test` | `deadbits.validation.unittests` | `tests` |
| `--benchmark` | `deadbits.validation.benchmark` | nonempty `benchmarks` |

`request` is the frozen `deadbits.diagnostics.ValidationRequest`, with resolved
`Path | None` fields `source_dir`, `samples_dir`, `expected_dir`, `corpus_dir`,
`evidence_dir`, plus `verbose` and canonical `app_version`. Binding it with
`functools.partial(run, request)` supplies the no-argument Runner protocol from
schema #9. Modules are imported from the installed application, never from the
user-supplied source path. A selected source suite is trusted local code; #11
owns safe subprocess execution and detailed outcome accounting.

This is the proposed CLI adapter boundary for runner PRs to implement/review;
#13 does not claim the other contributors have agreed to it. They retain their
isolated new modules. The CLI owns parsing, fresh destination protection,
envelope persistence, presentation and exit status. Runners own resource/content
validation, collection and detailed artifact persistence, following
[the evidence schema](VALIDATION-EVIDENCE.md). Missing inputs produce unavailable
evidence; failures are explicit. No independent scoring algorithm is added.
