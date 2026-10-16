"""Offline resource diagnostics and lazy validation-runner integration."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import platform
import sys

from .engine import ADAPTERS
from .model import FORMAT_NAMES
from .version import VERSION
from .validation.model import (Context, Environment, ReferenceEvidence, Resource,
                               TestEvidence, BenchmarkEvidence, ValidationEvidence)

RUNNERS = {'verify': 'reference', 'test': 'unittests', 'benchmark': 'benchmark'}


@dataclass(frozen=True)
class ValidationRequest:
    """Keyword-independent boundary for runner contributors (#10, #11, #12)."""
    source_dir: Path | None = None
    samples_dir: Path | None = None
    expected_dir: Path | None = None
    corpus_dir: Path | None = None
    evidence_dir: Path | None = None
    verbose: bool = False
    app_version: str = VERSION


def source_root():
    root = Path(__file__).resolve().parent.parent
    return root if (root / 'tests').is_dir() and (root / 'tools').is_dir() else None


def request_from(args):
    source = args.source_dir.resolve() if args.source_dir else source_root()
    kit = args.kit_dir.resolve() if args.kit_dir else (source / 'samples' / 'official' if source else None)
    def resolved(value, fallback=None):
        return value.resolve() if value is not None else fallback
    return ValidationRequest(source, resolved(args.samples_dir, kit / 'samples' if kit else None),
                             resolved(args.expected_dir, kit / 'expected_outputs' if kit else None),
                             resolved(args.corpus_dir), resolved(args.evidence_dir), args.verbose)


def resources(request):
    def directory(name, path, pattern):
        available = path is not None and path.is_dir() and any(path.glob(pattern))
        return Resource(name, available, str(path) if available else
                        'Missing or empty; supply the explicit local path. No download is attempted.')
    tools = request.source_dir / 'tools' if request.source_dir else None
    scorer_ready = tools is not None and all((tools / name).is_file()
                                             for name in ('evaluate.py', 'make_variants.py'))
    return (directory('source tests', request.source_dir / 'tests' if request.source_dir else None, 'test_*.py'),
            directory('samples', request.samples_dir, '*'),
            directory('organizer references', request.expected_dir, '*.json'),
            Resource('benchmark scoring tools', scorer_ready, str(tools) if scorer_ready else
                     'Missing evaluate.py/make_variants.py; supply --source-dir PATH to a trusted source kit.'))


def doctor(request):
    expected = set(FORMAT_NAMES) - {'UNKNOWN'}
    found = {adapter.NAME for adapter in ADAPTERS}
    rows = [('Python >= 3.10', sys.version_info >= (3, 10), platform.python_version()),
            ('Application version', True, VERSION),
            ('Format adapters', found == expected, ', '.join(sorted(found)))]
    for mode, module in RUNNERS.items():
        try:
            runner = importlib.import_module('deadbits.validation.' + module)
            ready = callable(getattr(runner, 'run', None))
        except ModuleNotFoundError as exc:
            if exc.name != 'deadbits.validation.' + module:
                raise
            ready = False
        rows.append((mode + ' runner', ready, 'available' if ready else 'not installed yet'))
    rows.extend((item.name, item.available, item.detail) for item in resources(request))
    if request.corpus_dir is not None:
        rows.append(('variant corpus', request.corpus_dir.is_dir(), str(request.corpus_dir)))
    # Validation resources are optional for ordinary recovery, but unavailable is
    # explicit for doctor. This checks presence only, never executes test sources.
    code = 1 if not all(row[1] for row in rows[:3]) else (0 if all(row[1] for row in rows) else 3)
    return rows, code


def unavailable(mode, detail):
    context = Context(app_version=VERSION, environment=Environment(platform.python_version(), platform.platform()),
                      provenance='live', recorded_at=datetime.now(timezone.utc).isoformat())
    fields = dict(context=context, resources=(Resource(mode + ' runner', False, detail),))
    if mode == 'verify':
        return ValidationEvidence(reference=ReferenceEvidence(**fields))
    if mode == 'test':
        return ValidationEvidence(tests=TestEvidence(**fields))
    return ValidationEvidence(benchmarks=(BenchmarkEvidence(**fields),))


def load_evidence(path, mode):
    # A saved run is always historical, including evidence originally labelled live.
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('saved evidence exceeds the 8 MiB presentation limit')
    evidence = ValidationEvidence.from_dict(json.loads(path.read_text(encoding='utf-8')))
    def historical(section):
        return replace(section, context=replace(section.context, provenance='historical', source=str(path)))
    if mode == 'verify' and evidence.reference is not None:
        return ValidationEvidence(reference=historical(evidence.reference))
    if mode == 'test' and evidence.tests is not None:
        return ValidationEvidence(tests=historical(evidence.tests))
    if mode == 'benchmark' and evidence.benchmarks:
        return ValidationEvidence(benchmarks=tuple(historical(row) for row in evidence.benchmarks))
    return unavailable(mode, 'Saved evidence has no requested section; no measurement was executed.')


def run_validation(mode, request):
    name = 'deadbits.validation.' + RUNNERS[mode]
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        return unavailable(mode, '%s is not installed yet (issue #%s). Use source tools meanwhile.' %
                           (name, {'verify': 10, 'test': 11, 'benchmark': 12}[mode]))
    runner = getattr(module, 'run', None)
    if not callable(runner):
        raise ValueError(name + ' must expose run(request) -> ValidationEvidence')
    if request.evidence_dir is None:
        return unavailable(mode, 'Supply --evidence-dir with a new directory for saved outputs and evidence.')
    destination = request.evidence_dir.resolve()
    # Resolve aliases before comparing, including symlinked parent directories.
    protected = [request.samples_dir, request.expected_dir, request.corpus_dir,
                 request.source_dir, source_root()]
    for root in protected:
        if root is not None and (destination == root.resolve() or root.resolve() in destination.parents
                                 or destination in root.resolve().parents):
            raise ValueError('evidence directory must be separate from source, samples, references and corpus')
    # A fresh destination prevents overwriting recovery report.json or earlier proof.
    destination.mkdir(parents=True, exist_ok=False)
    evidence = runner(request)
    if not isinstance(evidence, ValidationEvidence):
        raise ValueError(name + ' returned invalid validation evidence')
    if ((mode == 'verify' and evidence.reference is None) or
            (mode == 'test' and evidence.tests is None) or
            (mode == 'benchmark' and not evidence.benchmarks)):
        raise ValueError(name + ' omitted the requested evidence section')
    # Never replace an existing runner artifact or follow its symlink.
    with (destination / 'validation.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(evidence.to_dict(), stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write('\n')
    return evidence


def exit_code(evidence):
    return {'complete': 0, 'failed': 1, 'unavailable': 3}[evidence.status]
