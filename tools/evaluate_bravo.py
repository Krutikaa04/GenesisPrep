"""Measure false BRAVO identification on independently constructed ordinary text.

  python tools/evaluate_bravo.py [--json REPORT.json]

These negative controls are not BRAVO files. They exercise ambiguity around CR
paragraphs and DOS EOF suffixes, not arbitrary binary files or hidden judges.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deadbits.engine import salvage_bytes  # noqa: E402


def negative_cases():
    bodies = {
        'memo': b'First paragraph here\rSecond paragraph here\rThird paragraph here\r',
        'inventory': b'item,count\rbolts,120\rnuts,240\rwashers,360\r',
        'log': b'09:00 opened local file\r09:01 processed rows\r09:02 closed local file\r',
        'tabs': b'Name\tValue\rNorth\t12345\rSouth\t67890\rEast\t24680\r',
    }
    suffixes = {'none': b'', 'eof': b'\x1a', 'one_zero': b'\x1a\0',
                'two_zeros': b'\x1a\0\0', 'short_binary': b'\x1a\0\0\x06',
                'text': b'\x1aTEXT', 'zeros': b'\x1a' + bytes(15),
                'text_and_zeros': b'\x1a\0\0TEXT'}
    for name, body in bodies.items():
        for suffix_name, suffix in suffixes.items():
            yield name + '-' + suffix_name, body + suffix


def evaluate(decoder=salvage_bytes):
    cases = []
    for name, data in negative_cases():
        result = decoder(data, name + '.bin')
        cases.append({'case': name, 'size': len(data), 'format': result.format,
                      'status': result.status, 'records': len(result.records)})
    return {'schema_version': 1, 'negative_cases': len(cases),
            'false_bravo_identifications': sum(c['format'] == 'BRAVO' for c in cases),
            'unknown_cases': sum(c['format'] == 'UNKNOWN' for c in cases),
            'limitations': ['Constructed ordinary-text negatives, independent of pristine decoder output.',
                            'Marker plus a plausible binary trailer can still match unrelated text.',
                            'This corpus does not establish a general false-identification rate.'],
            'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    report = evaluate()
    if args.json:
        output = args.json.resolve()
        official = ROOT / 'samples' / 'official'
        if output == official or official in output.parents:
            parser.error('reports must be outside the read-only official kit')
        output.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('%d ordinary-text controls: %d false BRAVO identifications; %d UNKNOWN' %
          (report['negative_cases'], report['false_bravo_identifications'], report['unknown_cases']))
    return int(report['false_bravo_identifications'] != 0 or report['unknown_cases'] != report['negative_cases'])


if __name__ == '__main__':
    raise SystemExit(main())
