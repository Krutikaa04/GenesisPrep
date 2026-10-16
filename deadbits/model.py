"""Output model: the organizers' per-file JSON contract (OUTPUT-CONTRACT.md)."""

STATUSES = ("ok", "partial", "unsupported", "unrecognized", "failed")
KINDS = ("truncated", "crc_mismatch", "checksum_mismatch", "bad_length", "unparsed_bytes", "count_mismatch",
         "invalid_value", "oob_pointer", "index_missing", "header_checksum", "encrypted", "unknown_record")
FORMAT_NAMES = ("LIBRA-98", "LABLOG", "VAULT", "WKS", "WPD", "BRAVO", "CVT", "EBCDIC-DUMP", "WAD", "PAK", "UNKNOWN")


class Result:
    """One input file's outcome. `to_dict()` is exactly the per-file JSON."""

    def __init__(self, source_file: str, fmt: str = "UNKNOWN", status: str = "unrecognized"):
        self.source_file = source_file
        self.format = fmt
        self.status = status
        self.metadata = {}
        self.records = []
        self.damage = []
        self.notes = []   # report-only commentary (not in the per-file JSON)
        self.size = None  # input size in bytes; set by the engine so offsets can be clamped into the file

    def add_damage(self, kind: str, offset: int, detail: str, lossy: bool = True) -> None:
        if kind not in KINDS:
            raise ValueError("damage kind %r is not in the contract vocabulary" % kind)
        self.damage.append({"kind": kind, "offset": int(offset), "detail": detail, "lossy": bool(lossy)})

    def to_dict(self) -> dict:
        if not isinstance(self.source_file, str):
            raise ValueError("source_file must be a string")
        if self.status not in STATUSES:
            raise ValueError("status %r not in contract" % self.status)
        if self.format not in FORMAT_NAMES:
            raise ValueError("format %r not in contract" % self.format)
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")
        if not isinstance(self.records, list) or any(not isinstance(r, dict) for r in self.records):
            raise ValueError("records must be a list of objects")
        if not isinstance(self.damage, list):
            raise ValueError("damage must be a list")
        for item in self.damage:
            if (not isinstance(item, dict)
                    or set(item) != {"kind", "offset", "detail", "lossy"}
                    or item["kind"] not in KINDS
                    or type(item["offset"]) is not int
                    or not isinstance(item["detail"], str)
                    or type(item["lossy"]) is not bool):
                raise ValueError("invalid damage entry")
        if not isinstance(self.notes, list) or any(not isinstance(n, str) for n in self.notes):
            raise ValueError("notes must be a list of strings")
        damage = self.damage
        if self.size is not None:   # an offset must point inside the file (or exactly at EOF)
            damage = [dict(d, offset=max(0, min(d["offset"], self.size))) for d in damage]
        return {"source_file": self.source_file, "format": self.format, "status": self.status,
                "metadata": self.metadata, "records": self.records, "damage": damage}


def unverified(record: dict, *issues: str) -> dict:
    """Mark a recovered-but-unverified record (contract: verified=false and/or issues)."""
    record["verified"] = False
    if issues:
        record["issues"] = sorted(set(record.get("issues", [])) | set(issues))
    return record
