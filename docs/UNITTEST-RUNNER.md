# Source test runner

Issue #11 owns `deadbits/validation/unittests.py`, its synthetic-suite tests,
and this document. It uses the schema and runner/presenter boundary from #9.
No shared recovery CLI, decoder, schema, fixture, or recovery JSON changes are
needed. CLI integration remains with #13.

Run explicitly selected, trusted local Python test sources:

```console
python -m deadbits.validation.unittests --tests-dir tests --output-dir out/tests
python -m deadbits.validation.unittests --source-kit /path/to/source-checkout --output-dir out/tests --verbose
```

`--source-kit` selects the kit's `tests/` directory. A portable installation
does not contain the source suite; with no selection or a missing directory,
the runner saves unavailable evidence and explains these source-kit options.
It never silently discovers tests in the current directory. `--pattern` selects
a filename glob (default `test_*.py`). The output must be outside the selected
test directory. Arguments, including paths with spaces and shell characters,
are passed as a subprocess argument list without shell interpolation.

The API `run_tests(output_dir=..., tests_dir=... | source_kit=..., pattern=...,
timeout=300, commit=None)` returns a `ValidationEvidence` with its test section.
Bind its arguments, for example with `functools.partial`, to use the zero-argument
`Runner` protocol. Discovery and execution run in a fresh Python child process
using the current interpreter and application. Source-kit tests must be compatible
with that application; the runner does not install or replace application code.
The child uses the test directory's parent as its working directory. Fixture
resources must accompany the source kit. Re-entering an active selection is
refused; different nested synthetic suites remain supported, with a depth limit.
The default timeout is 300 seconds; adjust `--timeout` for larger suites.

Each invocation writes three separate validation artifacts:

- `evidence.json`: schema-1 `ValidationEvidence`, with the test outcomes, live
  timestamp, canonical app version, interpreter/platform and artifact hashes.
- `summary.json`: discovered and run counts, six outcome counts, fixture-event
  count, selection/pattern, completion problems, and a parent-test outcome ledger.
- `tests.log`: verbose unittest output including individual subtest tracebacks,
  discovery/import errors, fixture diagnostics, stdout, and stderr.

Console output is concise by default. `--verbose` also displays the saved log.
Exit codes are 0 for a passing test section, 1 for failed, and 2 for unavailable
or invalid invocation. The recovery command's zero-exit behavior is unchanged.
Repeated invocations replace the three artifacts; do not share one output
directory between concurrent runs. Persistence failures are reported as errors.

## Accounting

Counts come from actual unittest callbacks, never a hardcoded suite size.
Successful, failed, erroring, skipped, expected-failure, and unexpected-success
outcomes are mutually exclusive for each parent test. Multiple subtest or cleanup
events never inflate the parent denominator. Error takes precedence over failure,
then unexpected success, skip, expected failure, and success. Successful subtests
do not add tests; a partially skipped parent is conservatively classified skipped
unless it also failed or errored. Detailed subtest events remain in the log.

`discovered` is unittest's pre-run `countTestCases()` (including import-error
placeholders). `run` is its `testsRun`, which counts started test methods.
Class/module setup or teardown errors/skips do not start test methods: they are
explicit `kind: fixture` ledger entries and contribute one corresponding outcome
each. Thus evidence `total` equals `run + fixture_events` for completed standard
unittest runs. A class setup error can have discovered=2, run=0, errors=1; a
class teardown error can coexist with completed passing methods. Neither is green.
Class/module fixture skips similarly remain explicit rather than becoming passes.

Discovery/import errors make the source resource unavailable, while preserving
known error counts and tracebacks. Empty and skip-only suites are unavailable.
Unexpected successes fail the run; expected failures remain separate from passes.
Worker timeouts, early exits, discovery interruption, or infrastructure exceptions
produce unavailable evidence with unknown outcome counts, rather than keeping a
stale success or interpreting a partial run as complete. The timeout terminates
the worker; tests remain responsible for subprocesses they start themselves.

The source path/pattern is an identity label, not a content hash. Dataset hash
stays unknown because arbitrary tests can read fixtures and dependencies outside
the discovered Python sources. Commit stays unknown unless a caller supplies the
measured application commit. Loading saved evidence does not rerun tests; presenters
must label saved runs historical as described in `VALIDATION-EVIDENCE.md`.
