"""Measure damaged-sample recovery; distinguish references from regression checks.

  python tools/evaluate.py [--json REPORT.json]
  python tools/make_variants.py /tmp/deadbits-variants
  python tools/evaluate.py --variants /tmp/deadbits-variants

Seven organizer references provide independent expected records. For other
recognized files, original verified decoder output is ONLY a regression
baseline, not proof of accuracy. Original unverified records and optional
partial reference records are excluded from recovery denominators. New records
from incomplete regression baselines are reported as unassessed, not assumed
wrong. Files with no assessable records have recovery rate null (never 100%).

These mutations do not establish the true contents of unreferenced samples or
predict hidden-judge results. In formats without checksums, plausible corruption
can remain undetectable. Wrong verified records are measured against the stated
baseline, including inherent checksum limitations; a zero is not a guarantee.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadbits.engine import salvage_bytes  # noqa: E402
from make_variants import DEFAULT_SAMPLES, MUTATIONS, OFFICIAL, sample_files, sha256, variants  # noqa: E402

DEFAULT_EXPECTED = ROOT / 'samples' / 'official' / 'expected_outputs'
KEYS = {'LIBRA-98': ['id'], 'LABLOG': ['sample'], 'VAULT': ['id'],
        'WKS': ['cell'], 'WPD': ['index'], 'BRAVO': ['index'], 'CVT': ['slot'],
        'EBCDIC-DUMP': ['student_id'], 'WAD': ['name'], 'PAK': ['name']}
FIELDS = {
    'LIBRA-98': 'id title author year price_cents copies isbn checked_out deleted reference_only due_date',
    'LABLOG': 'sample time_ms values',
    'VAULT': 'id name type size sha256 compressed text width height',
    'WKS': 'cell row col type value alignment number_format iso_date cached_value formula_raw_hex',
    'WPD': 'index type text', 'BRAVO': 'index text', 'CVT': 'slot text',
    'EBCDIC-DUMP': 'student_id name dob gpa credits status balance',
    'WAD': 'name offset size sha256', 'PAK': 'name offset size sha256'}
COUNTERS = ('cases', 'changed_cases', 'crashes', 'expected_records',
            'recovered_records', 'correct_records', 'wrong_records',
            'false_verified_records', 'incomplete_records', 'missing_records',
            'unexpected_records', 'unassessed_records', 'optional_records',
            'detection_cases', 'detected_cases', 'unknown_cases',
            'unknown_stayed_unknown')


def is_verified(record):
    return record.get('verified') is not False and not record.get('issues')


def record_key(record, keys):
    if not keys or any(k not in record for k in keys):
        return None
    # JSON also handles malformed unhashable key values without raising.
    return json.dumps([record[k] for k in keys], sort_keys=True, ensure_ascii=True)


def graded(record, fmt):
    return {k: record[k] for k in FIELDS.get(fmt, '').split() if k in record}


def make_baseline(original, expected=None):
    """Return source truth with its limitations explicit and machine-readable."""
    fmt = expected['format'] if expected else original['format']
    keys = expected.get('match_on', KEYS.get(fmt, [])) if expected else KEYS.get(fmt, [])
    if expected is not None:
        records = [graded(r, fmt) for r in expected.get('records', [])]
        optional = [graded(r, fmt) for r in expected.get('optional_partial_records', [])]
        return dict(kind='organizer_reference', format=fmt, keys=keys,
                    records=records, optional=optional, exhaustive=True,
                    original_status=original['status'], excluded_unverified=0)
    known = original.get('records', [])
    records = [graded(r, fmt) for r in known if is_verified(r)]
    optional = [graded(r, fmt) for r in known if not is_verified(r)]
    return dict(kind='regression_baseline' if fmt in KEYS else 'no_record_baseline',
                format=fmt, keys=keys, records=records, optional=optional,
                exhaustive=original['status'] == 'ok' and not optional,
                original_status=original['status'], excluded_unverified=len(optional))


def compare_records(actual, baseline):
    """Count keys recovered separately from complete field equality and honesty.

    Duplicate output keys are not collapsed. A present unequal value is wrong;
    an omitted field is incomplete, not an invented value. Optional records can
    neither improve the recovery rate nor silently establish unknown fields.
    """
    counts = {k: 0 for k in COUNTERS}
    expected = baseline['records']
    counts['expected_records'] = len(expected)
    buckets = defaultdict(list)
    for i, record in enumerate(expected):
        key = record_key(record, baseline['keys'])
        if key is not None:
            buckets[key].append(i)
    optional = {record_key(r, baseline['keys']): r for r in baseline['optional']}
    used = set()
    for record in actual.get('records', []):
        key = record_key(record, baseline['keys']) if actual['format'] == baseline['format'] else None
        candidates = [i for i in buckets.get(key, []) if i not in used]
        if candidates:
            # Duplicate identities are matched once each, preferring exact fields.
            index = min(candidates, key=lambda i: sum(record.get(k) != v or k not in record
                                                       for k, v in expected[i].items()))
            used.add(index)
            truth = expected[index]
            counts['recovered_records'] += 1
            wrong = any(k in record and record[k] != v for k, v in truth.items())
            missing = any(k not in record for k in truth)
            counts['wrong_records'] += int(wrong)
            counts['false_verified_records'] += int(wrong and is_verified(record))
            counts['incomplete_records'] += int(missing)
            counts['correct_records'] += int(not wrong and not missing)
        elif key is not None and key in optional:
            counts['optional_records'] += 1
            counts['unassessed_records'] += 1
        elif baseline['exhaustive']:
            counts['unexpected_records'] += 1
            counts['wrong_records'] += 1
            counts['false_verified_records'] += int(is_verified(record))
        else:
            counts['unassessed_records'] += 1
    counts['missing_records'] = len(expected) - len(used)
    return counts


def decode(data, name, decoder):
    """Surface exceptions swallowed by the engine as well as escaping failures."""
    try:
        result = decoder(data, name)
        notes = getattr(result, 'notes', [])
        doc = result.to_dict() if hasattr(result, 'to_dict') else result
        crashed = any('decoder exception' in str(note).lower() for note in notes)
        return doc, crashed
    except Exception:  # noqa: BLE001 - measuring crashes must not stop the corpus
        return {'format': 'UNKNOWN', 'status': 'failed', 'records': []}, True


def load_references(expected_dir):
    if not Path(expected_dir).is_dir():
        raise ValueError('expected reference directory does not exist')
    references = {}
    for path in sorted(Path(expected_dir).glob('*.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        references[doc['file']] = doc
    return references


def load_corpus(directory, sources):
    """Validate persisted mutations against original bytes, not just their hashes."""
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        raise ValueError('unsupported variant manifest version')
    recorded_sources = {r['file']: r for r in manifest['sources']}
    if len(recorded_sources) != len(manifest['sources']) or set(recorded_sources) != set(sources):
        raise ValueError('manifest source list does not match the samples')
    for name, data in sources.items():
        if recorded_sources[name]['size'] != len(data) or recorded_sources[name]['sha256'] != sha256(data):
            raise ValueError('original source differs from manifest: ' + name)
    result = {}
    for item in manifest['variants']:
        name, kind, file = item['source'], item['mutation'], item['file']
        if name not in sources or kind not in MUTATIONS or Path(file).name != file:
            raise ValueError('invalid variant manifest entry')
        key = name, kind
        if key in result:
            raise ValueError('duplicate variant manifest entry')
        data = (directory / file).read_bytes()
        canonical = {k: (d, p) for k, d, p in variants(sources[name])}[kind]
        if (data != canonical[0] or item['parameters'] != canonical[1] or
                item['sha256'] != sha256(data) or item['size'] != len(data) or
                item['changed'] != (data != sources[name])):
            raise ValueError('variant does not match deterministic mutation: ' + file)
        result[key] = data
    if set(result) != {(name, kind) for name in sources for kind in MUTATIONS}:
        raise ValueError('manifest must contain all six variants for every source')
    return result


def rates(counts):
    result = dict(counts)
    denominator = counts['expected_records']
    result['record_recovery_rate'] = counts['recovered_records'] / denominator if denominator else None
    result['complete_record_rate'] = counts['correct_records'] / denominator if denominator else None
    total = counts['detection_cases']
    result['format_coverage_rate'] = counts['detected_cases'] / total if total else None
    return result


def aggregate(cases):
    counts = {k: sum(case[k] for case in cases) for k in COUNTERS}
    return rates(counts)


def evaluate(samples=DEFAULT_SAMPLES, expected=DEFAULT_EXPECTED, decoder=salvage_bytes,
             corpus=None):
    paths = sample_files(samples)
    sources = {p.name: p.read_bytes() for p in paths}
    references = load_references(expected)
    persisted = load_corpus(corpus, sources) if corpus is not None else None
    baselines, baseline_crashes, cases = {}, [], []
    for name, data in sources.items():
        original, crashed = decode(data, name, decoder)
        if crashed:
            baseline_crashes.append(name)
        baseline = make_baseline(original, references.get(name))
        if crashed and name not in references:
            baseline['kind'] = 'no_record_baseline'
            baseline['exhaustive'] = False
            baseline['records'] = []
        baselines[name] = baseline
        for mutation, damaged, parameters in variants(data):
            if persisted is not None:
                damaged = persisted[name, mutation]
            actual, crashed = decode(damaged, name, decoder)
            counts = compare_records(actual, baseline)
            known = baseline['format'] != 'UNKNOWN'
            counts.update(cases=1, changed_cases=int(damaged != data), crashes=int(crashed),
                          detection_cases=int(known), detected_cases=int(known and actual['format'] == baseline['format']),
                          unknown_cases=int(not known),
                          unknown_stayed_unknown=int(not known and actual['format'] == 'UNKNOWN'))
            cases.append(dict(source=name, mutation=mutation, parameters=parameters,
                              baseline=baseline['kind'], format=baseline['format'],
                              actual_format=actual['format'], status=actual['status'], **counts))
    groups = defaultdict(list)
    for case in cases:
        groups[(case['baseline'], case['format'])].append(case)
    # No-op variants remain in the case ledger, but cannot inflate benchmark rates.
    changed = [case for case in cases if case['changed_cases']]
    return {
        'schema_version': 1, 'samples': len(sources), 'variants': len(cases),
        'changed_variants': len(changed), 'unchanged_variants': len(cases) - len(changed),
        'baseline_crashes': baseline_crashes,
        'limitations': [
            'Organizer references and decoder-derived regression baselines are scored separately.',
            'Regression equality does not independently establish original data accuracy.',
            'Recovery denominators exclude original unverified and optional partial records.',
            'Unknown formats and zero-record baselines have null record recovery rates.',
            'No-op mutations are listed but excluded from all summary rates.',
            'Novel records in incomplete regression baselines are unassessed, not assumed wrong.',
            'Missing fields are incomplete; only unequal asserted fields or unexpected keys are wrong.',
            'No-checksum formats can emit plausible corrupted values; measured zeros are not guarantees.',
            'These six deterministic mutations are regression evidence, not a hidden-judge prediction.'],
        'baselines': baselines,
        'summary': aggregate(changed),
        'by_baseline': {kind: aggregate([c for c in changed if c['baseline'] == kind])
                        for kind in sorted({c['baseline'] for c in cases})},
        'by_format': [dict(baseline=kind, format=fmt,
                           **aggregate([c for c in group if c['changed_cases']]))
                      for (kind, fmt), group in sorted(groups.items())],
        'cases': cases}


def percent(value):
    return 'n/a' if value is None else '%.1f%%' % (100 * value)


def print_report(report):
    print('%d samples; %d variants (%d changed, %d unchanged excluded)' %
          (report['samples'], report['variants'], report['changed_variants'], report['unchanged_variants']))
    print('All rows score changed variants only. Recovery = matched keys; complete = all expected fields equal.')
    print('%-20s %-12s %5s %11s %8s %9s %8s %8s %7s %10s' %
          ('Baseline', 'Format', 'Cases', 'Recovered', 'Rate', 'Complete', 'Wrong', 'False-V', 'Crashes', 'Coverage'))
    for row in report['by_format']:
        print('%-20s %-12s %5d %5d/%-5d %8s %9s %8d %8d %7d %10s' %
              (row['baseline'], row['format'], row['cases'], row['recovered_records'],
               row['expected_records'], percent(row['record_recovery_rate']),
               percent(row['complete_record_rate']), row['wrong_records'],
               row['false_verified_records'], row['crashes'], percent(row['format_coverage_rate'])))
    print('Baseline decode crashes: %d' % len(report['baseline_crashes']))
    for limitation in report['limitations']:
        print('- ' + limitation)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument('--expected', type=Path, default=DEFAULT_EXPECTED)
    parser.add_argument('--variants', type=Path)
    parser.add_argument('--json', type=Path, help='save the complete deterministic measurement ledger')
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.samples, args.expected, corpus=args.variants)
        if args.json:
            output = args.json.resolve()
            if output == OFFICIAL or OFFICIAL in output.parents:
                raise ValueError('evaluation reports must be outside the read-only official kit')
            args.json.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print_report(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
