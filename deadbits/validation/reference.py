"""Offline reference comparison with saved actual outputs and schema-1 evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys

from ..engine import MAX_INPUT_BYTES, salvage_bytes
from ..model import FORMAT_NAMES, KINDS, STATUSES
from ..version import VERSION
from .model import (Artifact, Context, Dataset, Environment, RecordAccuracy, ReferenceEvidence,
                    Resource, ValidationEvidence)

MAX_REFERENCE_BYTES = 8 * 1024 * 1024
MAX_REFERENCES = 10000
MAX_REFERENCE_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SAMPLE_TOTAL_BYTES = 128 * 1024 * 1024
KIT_HELP = ('Supply --kit-dir PATH containing samples/ and expected_outputs/, or '
            '--samples-dir and --expected-dir explicitly. Installed applications '
            'do not bundle the organizer kit; no download is attempted.')


def key(rec, match_on):
    return tuple(rec.get(k) for k in match_on)


def differences(actual, exp):
    """The organizer tool's exact matching rules, with machine-readable locations.

    Optional records are allowed by identity, unrequested metadata is ignored,
    duplicate identities use the last record, and damage matching checks kinds
    only (the legacy comparator does not compare lossy/offset/detail).
    """
    errors = []
    def add(kind, field, expected, got, detail, record_key=None):
        errors.append(dict(kind=kind, field=field, record_key=record_key,
                           expected=expected, actual=got, detail=detail))
    for field in ('format', 'status'):
        if actual[field] != exp[field]:
            add('field', field, exp[field], actual[field],
                '%s: got %r expected %r' % (field, actual[field], exp[field]))
    for field, value in exp.get('metadata', {}).items():
        got = actual['metadata'].get(field)
        if got != value:
            add('field', 'metadata.' + field, value, got,
                'metadata.%s: got %r expected %r' % (field, got, value))
    match_on = exp.get('match_on', ['id'])
    got = {key(r, match_on): r for r in actual['records']}
    want = {key(r, match_on): r for r in exp['records']}
    optional = {key(r, match_on) for r in exp.get('optional_partial_records', [])}
    for identity, record in want.items():
        current = got.get(identity)
        if current is None:
            add('missing_record', 'records', record, None,
                'missing record %s' % (identity,), list(identity))
            continue
        for field, value in record.items():
            if current.get(field) != value:
                add('field', 'records.' + field, value, current.get(field),
                    'record %s.%s: got %r expected %r' % (identity, field, current.get(field), value),
                    list(identity))
    for identity in got:
        if identity not in want and identity not in optional:
            add('extra_record', 'records', None, got[identity],
                'extra record %s' % (identity,), list(identity))
    damage = [d['kind'] for d in actual['damage']]
    expected_damage = exp.get('expected_damage', [])
    if not expected_damage and damage:
        add('unexpected_damage', 'damage', [], damage, 'unexpected damage: %s' % damage)
    for entry in expected_damage:
        if not any(kind in entry['any_of'] for kind in damage):
            add('missing_damage', 'damage', entry['any_of'], damage,
                'expected damage any_of %s, got %s' % (entry['any_of'], damage))
    return errors


def compare(actual, exp):
    """Compatibility API used by tools/compare_expected.py and existing tests."""
    return [error['detail'] for error in differences(actual, exp)]


def record_accuracy(actual, exp):
    """Score supplied fields only; ambiguous identities cannot produce a rate.

    File agreement retains legacy last-duplicate semantics. Record measurements
    deliberately require unique, complete keys instead of hiding duplicates.
    """
    match_on = exp.get('match_on', ['id'])
    def index(records):
        result = {}
        for record in records:
            if any(field not in record for field in match_on):
                raise ValueError('record accuracy requires all matching fields')
            identity = key(record, match_on)
            if identity in result:
                raise ValueError('record accuracy unavailable for duplicate record identities')
            result[identity] = record
        return result
    got, want = index(actual['records']), index(exp['records'])
    optional = index(exp.get('optional_partial_records', []))
    if want.keys() & optional.keys():
        raise ValueError('required and optional record identities overlap')
    recovered = len(got.keys() & want.keys())
    correct = sum(actual['format'] == exp['format'] and
                  all(field in got[identity] and got[identity][field] == value
                      for field, value in record.items())
                  for identity, record in want.items() if identity in got)
    return RecordAccuracy(expected=len(want), recovered=recovered, correct=correct,
                          wrong=recovered-correct, missing=len(want)-recovered,
                          unexpected=len(got.keys()-want.keys()-optional.keys()),
                          optional=len(got.keys() & optional.keys()))


def _strict_json(payload):
    def object_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('duplicate JSON key: ' + name)
            result[name] = value
        return result
    def invalid(value):
        raise ValueError('non-finite JSON number: ' + value)
    document = json.loads(payload.decode('utf-8'), object_pairs_hook=object_pairs, parse_constant=invalid)
    # Also rejects exponent overflow (e.g. 1e999).
    json.dumps(document, allow_nan=False)
    return document


def _validate_reference(document):
    if not isinstance(document, dict):
        raise ValueError('reference must be a JSON object')
    name = document.get('file')
    if (not isinstance(name, str) or not name or name in ('.', '..') or
            any(c in name for c in ('/', '\\', ':', '\x00'))):
        raise ValueError('reference file must name one portable input basename')
    if document.get('format') not in FORMAT_NAMES or document.get('status') not in STATUSES:
        raise ValueError('reference requires contract-valid format and status')
    if not isinstance(document.get('metadata', {}), dict):
        raise ValueError('metadata must be an object')
    match_on = document.get('match_on', ['id'])
    if (not isinstance(match_on, list) or not match_on or
            any(not isinstance(field, str) or not field for field in match_on) or
            len(set(match_on)) != len(match_on)):
        raise ValueError('match_on must contain unique nonempty field names')
    for group in ('records', 'optional_partial_records'):
        records = document.get(group, [] if group != 'records' else None)
        if not isinstance(records, list):
            raise ValueError(group + ' must be an array')
        for record in records:
            if not isinstance(record, dict) or any(field not in record for field in match_on):
                raise ValueError(group + ' requires record objects with all matching fields')
            try:
                hash(key(record, match_on))
            except TypeError as exc:
                raise ValueError('matching fields must have scalar values') from exc
    damage = document.get('expected_damage', [])
    if not isinstance(damage, list):
        raise ValueError('expected_damage must be an array')
    for entry in damage:
        if (not isinstance(entry, dict) or not isinstance(entry.get('any_of'), list) or
                not entry['any_of'] or any(kind not in KINDS for kind in entry['any_of']) or
                ('lossy' in entry and type(entry['lossy']) is not bool)):
            raise ValueError('expected_damage requires nonempty contract damage kinds and Boolean lossy')
    return document


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(document):
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True,
                       allow_nan=False) + '\n').encode('utf-8')


def _read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError('input must be a regular file, not a symlink: ' + str(path))
    with path.open('rb') as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError('input exceeds the %d-byte validation limit: %s' % (limit, path))
    return payload


def _prepare_output(output_dir, protected):
    candidate = Path(output_dir)
    if candidate.is_symlink():
        raise ValueError('evidence directory must not be a symlink')
    output = candidate.resolve()
    official = Path(__file__).resolve().parents[2] / 'samples' / 'official'
    for root in [*protected, official]:
        if root is None:
            continue
        root = Path(root).resolve()
        if output == root or root in output.parents or output in root.parents:
            raise ValueError('evidence must be separate from input, reference, source and official directories')
    # The CLI pre-creates an empty destination; standalone/API callers may do so too.
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('evidence directory must be new or empty; existing output is never overwritten')
    return output


def run_references(*, output_dir, samples_dir=None, expected_dir=None, source_dir=None,
                   app_version=VERSION, commit=None):
    """Measure explicitly selected resources. Missing/malformed input is unavailable.

    Both actual decoding and input hashes use the exact same bounded byte snapshot.
    No fixtures, external tools or current working directory are inferred here.
    """
    samples = Path(samples_dir).resolve() if samples_dir is not None else None
    expected = Path(expected_dir).resolve() if expected_dir is not None else None
    output = _prepare_output(output_dir, [samples, expected, source_dir])
    artifacts, cases, problems, manifest = [], [], [], []
    scores, scoring_problems, scored_files = [], [], set()
    def save(role, relative, payload):
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(payload)
        artifacts.append(Artifact(role, relative, _digest(payload)))
    samples_ready = samples is not None and samples.is_dir()
    references_ready = expected is not None and expected.is_dir()
    references, snapshots = [], {}
    if references_ready:
        try:
            paths = []
            for path in expected.glob('*.json'):
                paths.append(path)
                if len(paths) > MAX_REFERENCES:
                    raise ValueError('too many references (limit %d)' % MAX_REFERENCES)
            if not paths:
                raise ValueError('no JSON references found')
            reference_bytes = 0
            for path in sorted(paths):
                payload = _read(path, MAX_REFERENCE_BYTES)
                reference_bytes += len(payload)
                if reference_bytes > MAX_REFERENCE_TOTAL_BYTES:
                    raise ValueError('reference snapshots exceed the total byte limit')
                document = _validate_reference(_strict_json(payload))
                references.append((path.name, document, payload))
                manifest.append(dict(path='expected_outputs/' + path.name, sha256=_digest(payload)))
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            references_ready = False
            problems.append('Invalid/unreadable references: %s: %s' % (type(exc).__name__, exc))
    if not references_ready:
        problems.append(KIT_HELP)
    if samples_ready and references_ready:
        try:
            sample_bytes = 0
            for _, document, _ in references:
                name = document['file']
                if name not in snapshots:
                    snapshots[name] = _read(samples / name, MAX_INPUT_BYTES)
                    sample_bytes += len(snapshots[name])
                    if sample_bytes > MAX_SAMPLE_TOTAL_BYTES:
                        raise ValueError('sample snapshots exceed the total byte limit')
                    manifest.append(dict(path='samples/' + name, sha256=_digest(snapshots[name])))
        except (OSError, ValueError) as exc:
            samples_ready = False
            problems.append('Missing/unreadable sample: %s: %s' % (type(exc).__name__, exc))
    if not samples_ready:
        problems.append(KIT_HELP)
    complete = samples_ready and references_ready
    comparisons_ready = complete
    if complete:
        for index, (reference_name, document, payload) in enumerate(references, 1):
            actual_name, expected_name = 'actual/%04d.json' % index, 'expected/%04d.json' % index
            save('expected', expected_name, payload)
            case = dict(file=document['file'], reference=reference_name, actual=None,
                        expected=expected_name, matched=None, differences=[])
            try:
                actual = salvage_bytes(snapshots[document['file']], document['file']).to_dict()
            except Exception as exc:
                comparisons_ready = False
                case['problem'] = 'Decoder did not produce a result: %s: %s' % (type(exc).__name__, exc)
            else:
                # Save the actual even if an unusable comparison key prevents scoring.
                save('actual', actual_name, _json_bytes(actual))
                case['actual'] = actual_name
                try:
                    case['differences'] = differences(actual, document)
                    case['matched'] = not case['differences']
                except (TypeError, ValueError, KeyError) as exc:
                    comparisons_ready = False
                    case['problem'] = 'Comparison could not complete: %s: %s' % (type(exc).__name__, exc)
                if case['matched'] is not None:
                    try:
                        if document['file'] in scored_files:
                            raise ValueError('multiple reference answers for the same input file')
                        score = record_accuracy(actual, document)
                        scores.append(score)
                        scored_files.add(document['file'])
                        case['record_accuracy'] = score.to_dict()
                    except (TypeError, ValueError, KeyError) as exc:
                        case['record_accuracy_problem'] = str(exc)
                        scoring_problems.append('%s: %s' % (reference_name, exc))
            if 'problem' in case:
                problems.append('%s: %s' % (reference_name, case['problem']))
            cases.append(case)
    complete = complete and comparisons_ready
    matched = sum(case['matched'] for case in cases) if complete else None
    total = len(references) if references_ready else None
    score = None
    if complete and not scoring_problems:
        score = RecordAccuracy(**{name: sum(getattr(item, name) for item in scores)
                                  for name in RecordAccuracy.__dataclass_fields__})
    score_detail = ('; '.join(scoring_problems) if scoring_problems else
                    'Reference comparison did not complete.' if not complete else None)
    dataset_hash = None
    if complete:
        manifest.sort(key=lambda entry: entry['path'])
        canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        dataset_hash = _digest(canonical)
        save('dataset_manifest', 'dataset-manifest.json', _json_bytes(manifest))
    save('comparison', 'comparison.json', _json_bytes(dict(cases=cases, problems=problems)))
    save('summary', 'summary.json', _json_bytes(dict(matched=matched, total=total, compared=sum(case['matched'] is not None for case in cases),
                                                  complete=complete, problems=problems,
                                                  record_accuracy=score.to_dict() if score is not None else None,
                                                  record_accuracy_detail=score_detail)))
    context = Context(app_version=app_version, commit=commit,
        dataset=Dataset(identity='samples=%s; references=%s' % (samples, expected), sha256=dataset_hash),
        environment=Environment(platform.python_version(), platform.platform()), provenance='live',
        recorded_at=datetime.now(timezone.utc).isoformat())
    resources = (Resource('comparison execution', comparisons_ready,
                          None if comparisons_ready else '; '.join(problems) or KIT_HELP),
                 Resource('samples', samples_ready, str(samples) if samples_ready else KIT_HELP),
                 Resource('organizer references', references_ready,
                          str(expected) if references_ready else '; '.join(problems)))
    evidence = ValidationEvidence(reference=ReferenceEvidence(context=context, resources=resources,
                                  artifacts=tuple(artifacts), matched=matched, total=total,
                                  record_accuracy=score, record_accuracy_detail=score_detail))
    # Standalone evidence is also usable by --verify --evidence-file. The CLI owns
    # its separate validation.json envelope and will persist the returned object.
    with (output / 'reference-evidence.json').open('xb') as stream:
        stream.write(_json_bytes(evidence.to_dict()))
    return evidence


def run(request):
    """Issue #13 adapter; the CLI owns its fresh evidence directory/envelope."""
    return run_references(output_dir=request.evidence_dir, samples_dir=request.samples_dir,
                          expected_dir=request.expected_dir, source_dir=request.source_dir,
                          app_version=request.app_version)


def main(argv=None):
    from .. import presentation
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit-dir', type=Path)
    parser.add_argument('--samples-dir', type=Path)
    parser.add_argument('--expected-dir', type=Path)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    try:
        evidence = run_references(output_dir=args.evidence_dir,
            samples_dir=args.samples_dir or (args.kit_dir / 'samples' if args.kit_dir else None),
            expected_dir=args.expected_dir or (args.kit_dir / 'expected_outputs' if args.kit_dir else None))
        presentation.emit(presentation.validation(evidence, args.verbose,
                              args.evidence_dir.resolve() / 'reference-evidence.json'), sys.stdout)
        return {'complete': 0, 'failed': 1, 'unavailable': 3}[evidence.status]
    except (OSError, ValueError) as exc:
        presentation.emit('salvage: reference validation error: ' + str(exc), sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
