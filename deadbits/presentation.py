"""Terminal dashboards from measured results; saved output stays plain text."""
import json
import os
from pathlib import Path
import shutil
import textwrap


def clean(value):
    """Keep paths/decoder messages from injecting terminal control sequences."""
    text = str(value)
    return ''.join(c if c.isprintable() else '\\x%02x' % ord(c) for c in text)


def table(headers, rows):
    cells = [[clean(value) for value in row] for row in [headers, *rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    if sum(widths) + 2*(len(headers)-1) > width()-4:
        return '\n\n'.join('\n'.join('%s: %s' % pair for pair in zip(cells[0], row))
                           for row in cells[1:])
    return '\n'.join('  '.join(value.ljust(width) for value, width in zip(row, widths)).rstrip()
                     for row in cells)


def width():
    return max(28, min(96, shutil.get_terminal_size(fallback=(88, 24)).columns))


def panel(title, text):
    """ASCII borders, bounded wrapping and safe data, also on narrow terminals."""
    inner = width()-4
    border = '+' + '-'*(inner+2) + '+'
    lines = [border]
    for line in [title, '-'*min(len(title), inner), *str(text).splitlines()]:
        for part in textwrap.wrap(clean(line), inner, replace_whitespace=False,
                                  drop_whitespace=True) or ['']:
            lines.append('| ' + part.ljust(inner) + ' |')
    return '\n'.join([*lines, border])


def banner(mode):
    return panel('DEADBITS  /  ' + mode, 'Offline legacy recovery\nRead bytes  ->  identify  ->  recover  ->  report honestly')


def bar(numerator, denominator, size=18):
    if numerator is None or not denominator:
        return '[' + '?'*size + ']'
    filled = min(size, max(1 if numerator else 0, int(size*numerator/denominator)))
    return '[' + '#'*filled + '.'*(size-filled) + ']'


def meter(label, value):
    return '%s\n  %s  %s' % (label, bar(value.numerator, value.denominator), ratio(value))


_STATUS = dict(ok='No loss detected', partial='Some data lost or unverified',
               unsupported='Recognized; decoding unsupported',
               unrecognized='Insufficient format evidence', failed='Could not recover safely')


def record_card(record):
    uncertain = record.get('verified') is False or bool(record.get('issues'))
    title = 'Unverified record:' if uncertain else 'Recovered fields:'
    rows = []
    for name, value in record.items():
        rows.append((name.replace('_', ' '), json.dumps(value, ensure_ascii=True)))
    return panel(title, ('[!] Check issues before using these values.\n' if uncertain else
                        'Fields read from this input; integrity checks have limits.\n') +
                        table(('Field', 'Recovered value'), rows))


def byte_change(name, mutation, source_size, input_size):
    if name == 'truncation':
        kept = int(24*input_size/source_size) if source_size else 0
        return panel('WHAT CHANGED  /  truncation',
                     '[' + '#'*kept + 'x'*(24-kept) + ']\n' +
                     '# bytes kept; x bytes removed (scaled view)\n' +
                     '%d original bytes -> %d kept; %d removed\n'
                     'Missing fields cannot be reconstructed from absent bytes.' %
                     (source_size, input_size, source_size-input_size))
    if name == 'checksum':
        offset = mutation['offset']
        position = min(23, int(24*offset/input_size)) if input_size else 0
        return panel('WHAT CHANGED  /  checksum',
                     '[' + '.'*position + 'X' + '.'*(23-position) + ']\n' +
                     'X marks the changed checksum byte (scaled view)\n' +
                     'Byte %d XOR %d; length stays %d bytes.\n'
                     'Readable fields can survive while integrity checks fail.' %
                     (offset, mutation['xor'], input_size))
    if name == 'unknown':
        return panel('WHAT CHANGED  /  unknown input',
                     '00  FF  00  FF\nSynthetic bytes; no supported format evidence.\n'
                     'Expected behavior: no invented records.')
    return panel('WHAT CHANGED  /  healthy input',
                 '%d bytes copied unchanged.\nStart with readable records before introducing damage.' % input_size)


def count(value):
    return 'unavailable' if value is None else str(value)


def ratio(value):
    counts = '%s/%s' % (count(value.numerator), count(value.denominator))
    return counts + (' (unavailable)' if value.value is None else ' (%.1f%%)' % (100 * value.value))


def recovery(report, verbose=False):
    total = len(report['files'])
    records = sum(row['records'] for row in report['files'])
    damage = sum(row['damage'] for row in report['files'])
    rows = [(status, bar(number, total, 12), number, _STATUS.get(status, status))
            for status, number in report['totals'].items()]
    text = banner('RECOVERY') + '\n' + panel('Recovery: %d files' % total,
            'Recovered records: %d; damage entries: %d\n\n' % (records, damage) +
            table(('Status', 'Files / batch', 'Count', 'Meaning'), rows) +
            '\n\nBars show file counts in this batch, not record accuracy.')
    text += '\n' + panel('ACCURACY  /  not measured',
                         'Accuracy unavailable: recovery inputs have no supplied ground truth.\n'
                         'Use --verify with --samples-dir, --expected-dir and a new --evidence-dir to measure accuracy.')
    if verbose:
        text += '\n' + panel('FILE RESULTS', table(('File', 'Format', 'Status', 'Records', 'Damage'), [
            (r['file'], r['format'], r['status'], r['records'], r['damage']) for r in report['files']]))
    return text


def validation(evidence, verbose=False, evidence_file=None, compact=False):
    lines = [banner('VALIDATION'), 'Validation: ' + evidence.status]
    sections = []
    if evidence.reference is not None:
        item = evidence.reference
        sections.append(('References', item))
        lines += [panel('References: ' + item.status + '  /  ' + item.context.provenance,
                        meter('Reference agreement', item.agreement) +
                        '\nWhole-file comparison: format, status, requested fields and damage kinds.')]
        score = item.record_accuracy
        if score is None:
            lines.append(clean('Record accuracy unavailable: ' + (item.record_accuracy_detail or
                         'record measurements were not saved in this evidence.')))
        else:
            metrics = score.measurements
            lines += [panel('RECORD ACCURACY  /  supplied answers',
                meter('Recovered matching identities', metrics['recovery']) + '\n' +
                meter('Record accuracy (supplied fields)', metrics['accuracy']) + '\n' +
                meter('Record precision (supplied fields)', metrics['precision']) + '\n\n' +
                table(('Record outcome', 'Count'), [
                ('Wrong matching records', score.wrong), ('Missing expected records', score.missing),
                ('Unexpected records', score.unexpected),
                ('Optional records (not scored)', score.optional)]))]
            if not score.expected:
                lines.append('Record accuracy unavailable: references contain no required records.')
            lines.append('Scope: supplied reference files and fields only; files without answers are not scored.')
            lines.append('Optional partial records are excluded; format must match for a record to count as correct.')
    if evidence.tests is not None:
        item = evidence.tests
        sections.append(('Tests', item))
        lines += [panel('Tests: ' + item.status + '  /  ' + item.context.provenance,
            table(('Outcome', 'Count'), [
            (name.replace('_', ' '), count(getattr(item, name))) for name in item._outcomes] +
            [('total', count(item.total))]) + '\n\nTests check behavior; they do not measure recovery accuracy.')]
    if compact and evidence.benchmarks:
        lines.append(panel('BENCHMARKS  /  measured damage cases',
                           'Recovery = matching identities. Correct = all expected fields agree.\n'
                           'Unflagged = wrong records that still claim verification.\n'
                           'Fractions show exact counts, not percentages. See full evidence for rates.'))
        for baseline in dict.fromkeys(item.baseline for item in evidence.benchmarks):
            rows = [(item.format or 'all formats',
                     '%s/%s' % (count(item.recovered_records), count(item.expected_records)),
                     '%s/%s' % (count(item.complete_records), count(item.expected_records)),
                     count(item.wrong_records), count(item.false_verified_records), count(item.crashes),
                     item.status, item.context.provenance)
                    for item in evidence.benchmarks if item.baseline == baseline]
            lines.append(panel(baseline, table(('Format', 'Recovered', 'Correct', 'Wrong', 'Unflagged',
                                               'Crashes', 'State', 'Source'), rows)))
        lines.append('Regression equality is not independent accuracy evidence.')
    for item in evidence.benchmarks:
        label = 'Benchmark: %s / %s' % (item.baseline, item.format or 'all formats')
        sections.append((label, item))
        if compact:
            if item.status != 'measured':
                lines.append(clean(label + ' / ' + item.status + ' / ' + item.context.provenance))
        else:
            lines += [panel(label + ' / ' + item.status + ' / ' + item.context.provenance,
                '\n'.join(meter(name, value) for name, value in item.measurements.items()))]
        if not compact and item.baseline == 'regression_baseline':
            lines.append('Regression equality is not independent accuracy evidence.')
    if not sections:
        lines.append('No requested measurements are available.')
    for label, item in sections:
        context = item.context
        if not compact:
            lines.append(clean('%s provenance: %s' % (label, context.provenance)))
        elif context.provenance == 'historical':
            lines.append(clean('Saved proof: %s; version: %s; recorded: %s' %
                (label, context.app_version or 'unknown', context.recorded_at or 'unknown')))
        if verbose:
            lines.append(clean('Version: %s; commit: %s; recorded: %s' % (
                context.app_version or 'unknown', context.commit or 'unknown',
                context.recorded_at or 'unknown')))
            lines.append(clean('Dataset: %s; SHA-256: %s' % (
                context.dataset.identity or 'unknown', context.dataset.sha256 or 'unknown')))
            lines.append(clean('Python: %s; platform: %s; source: %s' % (
                context.environment.python_version or 'unknown', context.environment.platform or 'unknown',
                context.source or 'unknown')))
        for resource in item.resources:
            if verbose or resource.available is not True:
                lines.append(clean('%s: %s (%s)' % (resource.name, resource.available, resource.detail or 'no detail')))
        for artifact in item.artifacts:
            if compact:
                continue  # the evidence link below retains every artifact and hash
            path = Path(artifact.path)
            if evidence_file is not None and not path.is_absolute():
                path = evidence_file.parent / path
            lines.append(clean('%s: %s' % (artifact.role, path)))
            if verbose:
                lines.append('Artifact SHA-256: ' + (artifact.sha256 or 'unknown'))
    lines.append('Reference agreement, test outcomes and record recovery are separate measurements.')
    if compact and evidence_file is not None:
        lines.append('Full evidence: ' + clean(evidence_file))
    return '\n'.join(lines)


def emit(text, stream):
    """Redirected/legacy Windows streams may not support every filename glyph."""
    encoding = getattr(stream, 'encoding', None) or 'utf-8'
    # Color only application-drawn borders on capable interactive terminals.
    # Redirected logs/transcripts stay plain; NO_COLOR/TERM=dumb disable it.
    color = (getattr(stream, 'isatty', lambda: False)() and 'NO_COLOR' not in os.environ
             and os.environ.get('TERM') not in (None, 'dumb')
             and (os.name != 'nt' or 'WT_SESSION' in os.environ or 'ANSICON' in os.environ))
    if color:
        text = '\n'.join('\x1b[36m' + line + '\x1b[0m' if line.startswith('+---') else line
                         for line in text.split('\n'))
    stream.write((text + '\n').encode(encoding, errors='backslashreplace').decode(encoding))
    stream.flush()
