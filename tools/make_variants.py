"""Make a deterministic damage corpus without modifying the source samples.

Usage: python tools/make_variants.py OUTPUT_DIR [--samples SAMPLES_DIR]
Six cases are emitted for every top-level regular sample, even empty files.
The manifest records no-op mutations so they cannot inflate recovery evidence.
Only Python's standard library is used; no network access is needed.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = ROOT / 'samples' / 'official' / 'samples'
OFFICIAL = (ROOT / 'samples' / 'official').resolve()
MUTATIONS = ('truncate_10', 'truncate_50', 'truncate_90', 'one_byte_short',
             'single_byte_corrupt', 'zero_block')


def variants(data):
    """Yield (name, mutated_bytes, reproducible_mutation_details)."""
    size = len(data)
    for percent in (10, 50, 90):
        keep = size * percent // 100
        yield 'truncate_%d' % percent, data[:keep], {'keep_bytes': keep}
    keep = max(0, size - 1)
    yield 'one_byte_short', data[:keep], {'keep_bytes': keep}
    offset = size // 2
    damaged = bytearray(data)
    if size:
        damaged[offset] ^= 0xff
    yield 'single_byte_corrupt', bytes(damaged), {'offset': offset, 'xor': 255,
                                                'length': int(bool(size))}
    # Centre a contiguous block of up to 32 bytes on the midpoint.
    length = min(32, size)
    offset = max(0, (size - length) // 2)
    damaged = bytearray(data)
    damaged[offset:offset + length] = bytes(length)
    yield 'zero_block', bytes(damaged), {'offset': offset, 'length': length}


def sample_files(samples):
    """Match the CLI's non-recursive input listing, excluding symlinks."""
    return sorted(p for p in Path(samples).iterdir()
                  if p.is_file() and not p.is_symlink())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def create_corpus(samples, output):
    """Write corpus files and manifest. Refuse to write inside source fixtures."""
    samples, output = Path(samples).resolve(), Path(output).resolve()
    if output == samples or samples in output.parents or output == OFFICIAL or OFFICIAL in output.parents:
        raise ValueError('output directory must be outside the source samples')
    paths = sample_files(samples)
    # Plan before writing, including collisions with a source file or manifest.
    names = [p.name + '.' + kind + '.bin' for p in paths for kind in MUTATIONS]
    if len(names) != len(set(names)) or 'manifest.json' in names:
        raise ValueError('variant filenames collide')
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).is_symlink() for name in names + ['manifest.json']):
        raise ValueError('refusing to overwrite a symlink in the variant corpus')
    manifest = {'version': 1, 'sources': [], 'variants': []}
    for path in paths:
        data = path.read_bytes()
        manifest['sources'].append({'file': path.name, 'size': len(data),
                                    'sha256': sha256(data)})
        for kind, damaged, details in variants(data):
            name = path.name + '.' + kind + '.bin'
            (output / name).write_bytes(damaged)
            manifest['variants'].append({
                'source': path.name, 'file': name, 'mutation': kind,
                'parameters': details, 'size': len(damaged),
                'sha256': sha256(damaged), 'changed': damaged != data})
    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--samples', type=Path, default=DEFAULT_SAMPLES)
    args = parser.parse_args(argv)
    try:
        manifest = create_corpus(args.samples, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    changed = sum(v['changed'] for v in manifest['variants'])
    print('%d samples; %d variants; %d changed; %d unchanged' %
          (len(manifest['sources']), len(manifest['variants']), changed,
           len(manifest['variants']) - changed))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
