"""Issue #16: independent M1/M2 truth, never pristine decoder output as truth.

Existing fixture writers pack values chosen by tests, using only stdlib codecs,
struct and independent checksum implementations. No official input is read here.
Run with --measure for deterministic case/field/verification counts.
"""
from dataclasses import dataclass, field
import hashlib
import json
import struct
import sys
import unittest

from helpers import check_contract, salvage_bytes
from test_fmt_libra98 import KNOWN_RECORDS, known_file, record_bytes
from test_fmt_m1_accuracy import _lablog, _ebcdic
from test_fmt_vault import build as vault_file
from test_fmt_wks import sheet, label, integer, number, formula, blank
from test_fmt_cvt import seq, vlir, BLK


@dataclass
class Case:
    owner: str
    name: str
    data: bytes
    records: list
    truth: list
    status: str = "partial"
    damage: frozenset = frozenset()
    uncertain: frozenset = frozenset()  # output positions, preserving duplicates
    metadata: dict = field(default_factory=dict)
    negative: bool = False


def _patched(data, offset, fmt, value):
    data = bytearray(data)
    struct.pack_into(fmt, data, offset, value)
    return bytes(data)


def _negative(owner, data):
    return Case(owner, "ambiguous-recognition", data, [], [], "unrecognized", negative=True)


def libra_cases():
    truth = [dict(r) for r in KNOWN_RECORDS]
    data = known_file()
    yield Case("LIBRA-98", "pristine", data, truth, truth, "ok")
    duplicated = [truth[0], dict(truth[1], id=truth[0]["id"])]
    raw = bytearray(known_file(duplicated))
    raw[16 + len(record_bytes(duplicated[0])) - 1] ^= 1
    yield Case("LIBRA-98", "duplicate-id-plus-checksum", bytes(raw), duplicated, duplicated,
               damage=frozenset({"checksum_mismatch", "invalid_value"}), uncertain=frozenset({0, 1}))
    # The unprotected encoding flag changes rendering while the missing trailer
    # prevents authenticating that flag. Choose the alternate rendering ourselves.
    raw = bytearray(data[:16 + len(record_bytes(truth[0])) + 7])
    raw[5] ^= 1
    rendered = dict(truth[0], title="Caf\u201a", author="Zo\u2030")
    yield Case("LIBRA-98", "encoding-flag-plus-truncation", bytes(raw),
               [rendered, {"id": 42}], truth, damage=frozenset({"truncated"}), uncertain=frozenset({0, 1}))
    three = [dict(truth[0], title="First", author="A"),
             dict(truth[1], title="Victim"), dict(truth[1], id=43, title="Last")]
    raw = bytearray(known_file(three))
    start = 16 + len(record_bytes(three[0]))
    raw[start + 1] = 0
    raw[start + len(record_bytes(three[1])) - 1] ^= 1
    yield Case("LIBRA-98", "length-plus-record-checksum", bytes(raw), [three[0], three[2]], three,
               damage=frozenset({"bad_length", "checksum_mismatch"}))
    yield _negative("LIBRA-98", b"LB97" + data[4:])


def lablog_cases():
    base, blocks, _ = _lablog(2)
    truth = [dict(r) for r in base.records]
    yield Case("LABLOG", "pristine", base.data, truth, truth, "ok", metadata=base.metadata)
    sample_start = 32 + len(blocks[0])
    raw = bytearray(base.data[:-2])
    raw[30] ^= 1
    raw[sample_start + len(blocks[1]) - 1] ^= 1
    yield Case("LABLOG", "header-and-block-crc-plus-truncation", bytes(raw), truth, truth,
               damage=frozenset({"header_checksum", "crc_mismatch", "truncated"}), uncertain=frozenset(range(3)))
    raw = _patched(base.data[:-2], sample_start + 2, "<H", 65535)
    yield Case("LABLOG", "length-repair-plus-truncation", raw, truth, truth,
               damage=frozenset({"bad_length", "truncated"}))
    yield _negative("LABLOG", b"LLOG" + bytes(60))


def ebcdic_cases():
    base, next_block = _ebcdic(3)
    truth = [dict(r) for r in base.records]
    yield Case("EBCDIC-DUMP", "pristine", base.data, truth, truth, "ok", metadata=base.metadata)
    raw = bytearray(base.data)
    raw[next_block + 35] = 0xff  # impossible packed DOB digit
    struct.pack_into(">H", raw, next_block + 43, 18)  # expected trailer total remains 51
    expected = [truth[0], dict(truth[1], dob=None, credits=18), truth[2]]
    yield Case("EBCDIC-DUMP", "packed-field-plus-total-disagreement", bytes(raw), expected, truth,
               damage=frozenset({"invalid_value", "checksum_mismatch"}), uncertain=frozenset(range(3)))
    raw = bytearray(base.data[:next_block + 4 + 48 + 20])
    raw[next_block + 6] = 1  # bad RDW reserved bytes before a cut sibling
    yield Case("EBCDIC-DUMP", "descriptor-plus-truncated-sibling", bytes(raw), [truth[0]], truth,
               damage=frozenset({"bad_length", "truncated"}))
    raw = bytearray(base.data)
    raw[29:37] = "19990230".encode("cp037")
    yield Case("EBCDIC-DUMP", "invalid-header-with-independent-records", bytes(raw), truth, truth,
               damage=frozenset({"invalid_value"}), metadata={"run_date": None})
    yield _negative("EBCDIC-DUMP", bytes(raw[:next_block]))


def vault_cases():
    payloads = ["caf\u00e9\nAAAA".encode("utf-8"), b"\x00\x7f\x90\xff"]
    entries = [dict(id=501, type=1, flags=3, name="note.txt", data=payloads[0]),
               dict(id=502, type=3, flags=0, name="raw.bin", data=payloads[1])]
    truth = [dict(id=501, name="note.txt", type="text", size=len(payloads[0]), compressed=True,
                  sha256=hashlib.sha256(payloads[0]).hexdigest(), text="caf\u00e9\nAAAA"),
             dict(id=502, name="raw.bin", type="binary", size=4, compressed=False,
                  sha256=hashlib.sha256(payloads[1]).hexdigest())]
    data = vault_file(entries)
    index = int.from_bytes(data[8:12], "little")
    yield Case("VAULT", "pristine", data, truth, truth, "ok",
               metadata={"entry_count": 2, "xor_key": 33, "flags": 0})
    raw = _patched(data[:index + 16 + 5], index + 8, "<I", len(data) + 100)
    expected = {k: v for k, v in truth[0].items() if k not in ("sha256", "text")}
    yield Case("VAULT", "block-pointer-plus-index-truncation", raw, [expected], truth,
               damage=frozenset({"oob_pointer", "truncated"}), uncertain=frozenset({0}))
    # Duplicate identities and invalid UTF-8 must not hide a verified text claim.
    bad_payload = b"bad\x98"
    raw = vault_file([dict(entries[0], data=bad_payload, flags=0), dict(entries[1], id=501)])
    expected = [dict(truth[0], size=4, compressed=False, text="bad\u00ff",
                     sha256=hashlib.sha256(bad_payload).hexdigest()), dict(truth[1], id=501)]
    yield Case("VAULT", "duplicate-id-plus-invalid-utf8", raw, expected, [dict(truth[1], id=501)],
               damage=frozenset({"invalid_value"}), uncertain=frozenset({0, 1}))
    # Raw size/name facts can survive while an untrusted hash must be omitted.
    raw = _patched(data[:index + 16 + 5], 12, "<I", len(data) + 100)
    raw = _patched(raw, index + 14, "<H", len(payloads[0]) + 1)
    expected = dict(truth[0], name=None, size=len(payloads[0]) + 1)
    expected.pop("sha256")
    yield Case("VAULT", "names-and-size-plus-index-truncation", raw, [expected], truth,
               damage=frozenset({"oob_pointer", "bad_length", "truncated"}), uncertain=frozenset({0}))
    yield _negative("VAULT", b"VLT0" + data[4:])


def wks_cases():
    records = [label(0, 0, "Known"), integer(0, 1, 7), number(1, 1, 2.5), formula(2, 1, 9.5), blank(3, 1)]
    truth = [dict(cell="A1", col=0, row=0, type="label", value="Known", alignment="left"),
             dict(cell="A2", col=0, row=1, type="integer", value=7),
             dict(cell="B2", col=1, row=1, type="number", value=2.5),
             dict(cell="C2", col=2, row=1, type="formula", cached_value=9.5, formula_raw_hex="0b03"),
             dict(cell="D2", col=3, row=1, type="blank")]
    data = sheet(*records)
    yield Case("WKS", "pristine", data, truth, truth, "ok",
               metadata={"version_code": "0x0404", "declared_range": "A1:D6", "column_widths": {"A": 12}})
    data = sheet(records[0], integer(0, 1, 111), *records[1:])[:-2]
    pos = data.index(records[1])
    raw = _patched(data, pos + 2, "<H", 9)
    yield Case("WKS", "duplicate-cell-length-plus-truncation", raw, truth, truth,
               damage=frozenset({"bad_length", "truncated"}), uncertain=frozenset({1}))
    raw = sheet(label(0, 0, "caf\u00e9"), records[1], records[2],
                formula(2, 1, 9.5, tokens=b"\0\0"), records[4], eof=False)
    expected = [dict(truth[0], value="caf\u00e9"), truth[1], truth[2],
                dict(truth[3], formula_raw_hex="0000"), truth[4]]
    yield Case("WKS", "encoding-formula-plus-missing-eof", raw, expected, truth,
               damage=frozenset({"invalid_value", "truncated"}), uncertain=frozenset({0, 3}))
    yield _negative("WKS", b"\x01" + data[1:])


def cvt_cases():
    seq_truth = [dict(slot=0, text="Known\nsecond")]
    yield Case("CVT", "pristine-seq", seq("Known\nsecond"), seq_truth, seq_truth, "ok",
               metadata={"name": "Notes", "structure": "seq", "modified": "1991-03-14T09:30"})
    truth = [dict(slot=0, text="first"), dict(slot=5, text="second")]
    data = vlir({0: "first", 5: "second"})
    yield Case("CVT", "pristine-vlir", data, truth, truth, "ok")
    raw = bytearray(data[:4 * BLK + 3])
    raw[2 * BLK + 1] = 0  # invalid last-byte count, followed by a physically cut record
    yield Case("CVT", "index-length-plus-truncation", bytes(raw), [truth[0], dict(slot=5, text="sec")], truth,
               damage=frozenset({"bad_length", "truncated"}), uncertain=frozenset({0, 1}))
    raw = bytearray(data)
    raw[2 * BLK + 3] = 1  # zero-block slot with an impossible used-byte count
    raw[4 * BLK] = 0xc0  # PETSCII graphics has no established text equivalent
    yield Case("CVT", "ambiguous-index-plus-graphics", bytes(raw), [truth[0], dict(slot=5, text="\ufffdecond")], truth,
               damage=frozenset({"invalid_value"}), uncertain=frozenset({0, 1}))
    raw = _patched(data[:4 * BLK + 3], 0x1c, "<H", 9)
    yield Case("CVT", "header-index-disagreement-plus-truncation", raw, [truth[0], dict(slot=5, text="sec")], truth,
               damage=frozenset({"count_mismatch", "truncated"}), uncertain=frozenset({0, 1}))
    yield _negative("CVT", _patched(data, 0x22, "B", data[0x22] ^ 1))


BUILDERS = {"LIBRA-98": libra_cases, "LABLOG": lablog_cases, "EBCDIC-DUMP": ebcdic_cases,
            "VAULT": vault_cases, "WKS": wks_cases, "CVT": cvt_cases}


def assess(test, case):
    result = salvage_bytes(case.data, case.name)
    doc = check_contract(test, result, len(case.data), case.name)
    json.dumps(doc, allow_nan=False)
    test.assertEqual(doc["format"], "UNKNOWN" if case.negative else case.owner)
    test.assertEqual(doc["status"], case.status)
    plain = [{k: v for k, v in record.items() if k not in ("verified", "issues")} for record in doc["records"]]
    test.assertEqual(plain, case.records, (case.name, doc))
    test.assertTrue(case.damage <= {damage["kind"] for damage in doc["damage"]}, (case.name, doc))
    for key, value in case.metadata.items():
        test.assertIn(key, doc["metadata"])
        test.assertEqual(doc["metadata"].get(key), value, key)
    trusted = 0
    for index, record in enumerate(doc["records"]):
        verified = record.get("verified") is not False and not record.get("issues")
        if index in case.uncertain:
            test.assertFalse(verified, (case.name, index, record))
        if verified:
            trusted += 1
            test.assertIn(plain[index], case.truth, ("incorrect verified record", case.name, record))
    return dict(records=len(plain), fields=sum(len(record) for record in plain),
                verified_records=trusted, unverified_records=len(plain) - trusted,
                damage_entries=len(doc["damage"]))


def measure():
    """Fixture observations, not benchmark/organizer/hidden-score percentages."""
    rows = []
    for owner, builder in BUILDERS.items():
        for case in builder():
            try:
                metrics = assess(unittest.TestCase(), case)
                rows.append(dict(format=owner, case=case.name, passed=True,
                                 input_sha256=hashlib.sha256(case.data).hexdigest(), **metrics))
            except Exception as error:
                rows.append(dict(format=owner, case=case.name, passed=False,
                                 input_sha256=hashlib.sha256(case.data).hexdigest(), error=str(error)))
    return dict(corpus="issue-16-independent-compound-v1", cases=len(rows),
                passed=sum(row["passed"] for row in rows), rows=rows)


class IndependentCompoundKnownAnswers(unittest.TestCase):
    def check_format(self, owner):
        for case in BUILDERS[owner]():
            with self.subTest(format=owner, case=case.name):
                assess(self, case)

    def test_libra(self):
        self.check_format("LIBRA-98")

    def test_lablog(self):
        self.check_format("LABLOG")

    def test_ebcdic(self):
        self.check_format("EBCDIC-DUMP")

    def test_vault(self):
        self.check_format("VAULT")

    def test_wks(self):
        self.check_format("WKS")

    def test_cvt(self):
        self.check_format("CVT")


if __name__ == "__main__":
    if sys.argv[1:] == ["--measure"]:
        print(json.dumps(measure(), indent=2, sort_keys=True))
    else:
        unittest.main()
