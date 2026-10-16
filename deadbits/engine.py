"""Bounded, offline dispatch for trusted local format adapters."""
import importlib
import math
import os
import pkgutil
import re
import stat
from pathlib import Path

from . import formats
from ._limits import LEGACY_FORMATS, MAX_LEGACY_INPUT_BYTES, resource_issue
from .model import FORMAT_NAMES, Result

THRESHOLD = 0.5
MAX_INPUT_BYTES = 128 * 1024 * 1024
ANALYSIS_BYTES = 1024 * 1024
DETECTION_PREFIX_BYTES = 64 * 1024


def discover_adapters(package=formats):
    """Discover public modules deterministically; private helpers are ignored.

    Adapters must expose NAME, detect and decode. New contract format names
    still require the integrator to update the authoritative vocabulary.
    """
    adapters = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
        if info.ispkg or info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(package.__name__ + "." + info.name)
            if (getattr(mod, "NAME", None) in FORMAT_NAMES[:-1]
                    and callable(getattr(mod, "detect", None))
                    and callable(getattr(mod, "decode", None))):
                adapters.append(mod)
        except Exception:
            continue
    return adapters


ADAPTERS = discover_adapters()


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    return -sum(c / len(data) * math.log2(c / len(data)) for c in counts if c)


def unrecognized(data: bytes, name: str) -> Result:
    res = Result(name, "UNKNOWN", "unrecognized")
    res.size = len(data)
    prefix = data[:ANALYSIS_BYTES]
    strings = []
    for match in re.finditer(rb"[ -~]{4,256}", prefix):
        strings.append(match.group().decode("ascii"))
        if len(strings) == 10:
            break
    res.metadata = {
        "size": len(data),
        "first_64_bytes_hex": data[:64].hex(),
        "printable_strings": strings,
        "entropy_bits_per_byte": round(_entropy(prefix), 2),
    }
    if len(data) > len(prefix):
        res.metadata["analysis_prefix_bytes"] = len(prefix)
    return res


def _failure(name, detail, size=None, kind="unparsed_bytes"):
    res = Result(name, "UNKNOWN", "failed")
    res.size = size
    res.add_damage(kind, 0, detail, True)
    res.notes.append(detail)
    return res


def _oversized(name, size):
    res = _failure(name, "input exceeds the %d-byte safety limit" % MAX_INPUT_BYTES,
                   size, "bad_length")
    res.metadata = {"size": size, "max_input_bytes": MAX_INPUT_BYTES}
    return res


def salvage_bytes(data: bytes, name: str) -> Result:
    if len(data) > MAX_INPUT_BYTES:
        return _oversized(name, len(data))
    scored = []
    detection_prefix = None
    for mod in ADAPTERS:
        try:
            probe = data
            if mod.NAME in LEGACY_FORMATS and len(data) > MAX_LEGACY_INPUT_BYTES:
                if detection_prefix is None:
                    detection_prefix = data[:DETECTION_PREFIX_BYTES]
                probe = detection_prefix
            score = float(mod.detect(probe))
            if math.isfinite(score) and 0 <= score <= 1:
                scored.append((score, mod))
        except Exception:
            continue
    score, mod = max(scored, key=lambda item: item[0]) if scored else (0.0, None)
    if mod is None or score < THRESHOLD:
        return unrecognized(data, name)
    reason = resource_issue(data, mod.NAME)
    if reason:
        res = Result(name, mod.NAME, "failed")
        res.size = len(data)
        res.metadata = {"size": len(data)}
        res.add_damage("bad_length", 0, reason, True)
        res.notes.append(reason)
        return res
    try:
        res = mod.decode(data, name)
        if not isinstance(res, Result):
            raise TypeError("adapter did not return Result")
        if res.format != mod.NAME or res.source_file != name:
            raise ValueError("adapter result does not match its format/source")
        res.size = len(data)
        res.to_dict()
        return res
    except Exception as exc:
        res = Result(name, mod.NAME, "failed")
        res.size = len(data)
        res.add_damage("unparsed_bytes", 0, "decoder error: %s" % type(exc).__name__, True)
        res.notes.append("decoder exception: %r" % (exc,))
        return res


def salvage_file(path) -> Result:
    p = Path(path)
    fd = None
    try:
        before = p.lstat()
        if not stat.S_ISREG(before.st_mode):
            return _failure(p.name, "input is not a regular file; symlinks and special files are not followed")
        if before.st_size > MAX_INPUT_BYTES:
            return _oversized(p.name, before.st_size)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(p, flags)
        current = os.fstat(fd)
        if (not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)):
            return _failure(p.name, "input changed while being opened")
        if current.st_size > MAX_INPUT_BYTES:
            return _oversized(p.name, current.st_size)
        stream = os.fdopen(fd, "rb")
        fd = None
        with stream:
            data = stream.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            return _oversized(p.name, len(data))
        return salvage_bytes(data, p.name)
    except Exception as exc:
        return _failure(p.name, "could not read file: %s" % type(exc).__name__)
    finally:
        if fd is not None:
            os.close(fd)
