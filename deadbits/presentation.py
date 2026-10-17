"""Plain terminal presentation; measurements never imply arbitrary-input accuracy."""
from pathlib import Path


def clean(value):
    """Keep paths/decoder messages from injecting terminal control sequences."""
    text = str(value)
    return ''.join(c if c.isprintable() else '\\x%02x' % ord(c) for c in text)


def table(headers, rows):
    cells = [[clean(value) for value in row] for row in [headers, *rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    return '\n'.join('  '.join(value.ljust(width) for value, width in zip(row, widths)).rstrip()
                     for row in cells)


def count(value):
    return 'unavailable' if value is None else str(value)


def ratio(value):
    counts = '%s/%s' % (count(value.numerator), count(value.denominator))
    return counts + (' (unavailable)' if value.value is None else ' (%.1f%%)' % (100 * value.value))


def recovery(report, verbose=False):
    rows = [(status, number) for status, number in report['totals'].items()]
    text = 'Recovery: %d files\n' % len(report['files']) + table(('Status', 'Files'), rows)
    text += '\nRecovered records: %d; damage entries: %d' % (
        sum(row['records'] for row in report['files']), sum(row['damage'] for row in report['files']))
    text += '\nAccuracy unavailable: recovery inputs have no supplied ground truth.'
    if verbose:
        text += '\n' + table(('File', 'Format', 'Status', 'Records', 'Damage'), [
            (r['file'], r['format'], r['status'], r['records'], r['damage']) for r in report['files']])
    return text


def validation(evidence, verbose=False, evidence_file=None):
    lines = ['Validation: ' + evidence.status]
    sections = []
    if evidence.reference is not None:
        item = evidence.reference
        sections.append(('References', item))
        lines += ['References: ' + item.status, *table(('Measurement', 'Count'), [
            ('Reference agreement', ratio(item.agreement))]).split('\n')]
        score = item.record_accuracy
        if score is None:
            lines.append('Record accuracy unavailable: ' + (item.record_accuracy_detail or
                         'record measurements were not saved in this evidence.'))
        else:
            metrics = score.measurements
            lines += table(('Record measurement', 'Count / denominator'), [
                ('Recovered matching identities', ratio(metrics['recovery'])),
                ('Record accuracy (supplied fields)', ratio(metrics['accuracy'])),
                ('Record precision (supplied fields)', ratio(metrics['precision'])),
                ('Wrong matching records', score.wrong), ('Missing expected records', score.missing),
                ('Unexpected records', score.unexpected),
                ('Optional records (not scored)', score.optional)]).split('\n')
            if not score.expected:
                lines.append('Record accuracy unavailable: references contain no required records.')
            lines.append('Scope: supplied reference files and fields only; files without answers are not scored.')
            lines.append('Optional partial records are excluded; format must match for a record to count as correct.')
    if evidence.tests is not None:
        item = evidence.tests
        sections.append(('Tests', item))
        lines += ['Tests: ' + item.status, *table(('Outcome', 'Count'), [
            (name.replace('_', ' '), count(getattr(item, name))) for name in item._outcomes] +
            [('total', count(item.total))]).split('\n')]
    for item in evidence.benchmarks:
        label = 'Benchmark: %s / %s' % (item.baseline, item.format or 'all formats')
        sections.append((label, item))
        lines += [label + ' / ' + item.status, *table(('Measurement', 'Count / denominator'), [
            (name, ratio(value)) for name, value in item.measurements.items()]).split('\n')]
        if item.baseline == 'regression_baseline':
            lines.append('Regression equality is not independent accuracy evidence.')
    if not sections:
        lines.append('No requested measurements are available.')
    for label, item in sections:
        context = item.context
        lines.append('%s provenance: %s' % (label, context.provenance))
        if verbose:
            lines.append('Version: %s; commit: %s; recorded: %s' % (
                context.app_version or 'unknown', context.commit or 'unknown',
                context.recorded_at or 'unknown'))
            lines.append('Dataset: %s; SHA-256: %s' % (
                context.dataset.identity or 'unknown', context.dataset.sha256 or 'unknown'))
            lines.append('Python: %s; platform: %s; source: %s' % (
                context.environment.python_version or 'unknown', context.environment.platform or 'unknown',
                context.source or 'unknown'))
        for resource in item.resources:
            if verbose or resource.available is not True:
                lines.append('%s: %s (%s)' % (resource.name, resource.available, resource.detail or 'no detail'))
        for artifact in item.artifacts:
            path = Path(artifact.path)
            if evidence_file is not None and not path.is_absolute():
                path = evidence_file.parent / path
            lines.append('%s: %s' % (artifact.role, path))
            if verbose:
                lines.append('Artifact SHA-256: ' + (artifact.sha256 or 'unknown'))
    lines.append('Reference agreement, test outcomes and record recovery are separate measurements.')
    return '\n'.join(clean(line) for line in lines)


def emit(text, stream):
    """Redirected/legacy Windows streams may not support every filename glyph."""
    encoding = getattr(stream, 'encoding', None) or 'utf-8'
    stream.write((text + '\n').encode(encoding, errors='backslashreplace').decode(encoding))
