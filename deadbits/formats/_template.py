"""Copy to a public module to add an adapter. Private modules are not loaded.

Use a contract-approved NAME; additions to the vocabulary belong to the
integrator. Detection must require structural evidence. Decode must bound
all file-controlled lengths/counts and return Result on every byte sequence.
"""
from ..model import Result

NAME = "UNKNOWN"


def detect(data: bytes) -> float:
    return 0.0


def decode(data: bytes, source_file: str) -> Result:
    result = Result(source_file, NAME, "unrecognized")
    result.size = len(data)
    return result
