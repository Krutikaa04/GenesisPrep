#!/usr/bin/env bash
# Requires a running Docker daemon and the pinned base image already cached.
set -euo pipefail
SALVAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SALVAGE_PYTHON="${SALVAGE_PYTHON:-python3}"
SALVAGE_IMAGE="${SALVAGE_IMAGE:-deadbits:check}"
command -v docker >/dev/null || { echo 'Docker CLI is required.' >&2; exit 1; }
docker info >/dev/null
SALVAGE_TMP="$(mktemp -d "$SALVAGE_ROOT/.docker-check.XXXXXX")"
trap 'rm -rf "$SALVAGE_TMP"' EXIT
mkdir "$SALVAGE_TMP/native" "$SALVAGE_TMP/container"
# This forbids network for all Dockerfile RUN steps. Preload the pinned FROM
# image separately on a connected machine; no package install is performed.
docker build --network=none --pull=false -t "$SALVAGE_IMAGE" "$SALVAGE_ROOT"
PYTHONPATH="$SALVAGE_ROOT${PYTHONPATH:+:$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1 \
  "$SALVAGE_PYTHON" -m deadbits.cli "$SALVAGE_ROOT/samples/official/samples" "$SALVAGE_TMP/native"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  -v "$SALVAGE_ROOT/samples/official/samples:/in:ro" \
  -v "$SALVAGE_TMP/container:/out" "$SALVAGE_IMAGE" /in /out
# Compare names AND every byte, including report.json.
"$SALVAGE_PYTHON" - "$SALVAGE_TMP/native" "$SALVAGE_TMP/container" <<'PY'
from pathlib import Path
import sys
native, container = map(Path, sys.argv[1:])
names = sorted(p.name for p in native.iterdir())
if names != sorted(p.name for p in container.iterdir()):
    raise SystemExit('FAIL: output file lists differ')
for name in names:
    if (native / name).read_bytes() != (container / name).read_bytes():
        raise SystemExit('FAIL: byte mismatch: ' + name)
print('PASS: %d native/container JSON files are byte-identical; container network disabled' % len(names))
PY
