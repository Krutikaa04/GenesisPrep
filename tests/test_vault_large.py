"""Issue #17 VAULT slice: valid-large inputs and bounded hostile projections."""
import hashlib
import json
from pathlib import Path
import platform
import struct
import sys
import time
import tracemalloc
import unittest
from unittest.mock import patch

from helpers import check_contract
from deadbits import _limits, engine
from deadbits.formats import vault
from test_fmt_vault import build
from test_limits import vault_aliases


def valid_fixtures():
    for name, count, payload, typ, flags in (
        ("large-binary", 48, b"ABCD" * 15000, 3, 0),
        ("large-text", 48, b"Known text\n" * 4500, 1, 0),
        ("low-expansion-rle", 80, b"AB" * 600, 3, 1),
    ):
        entries = [dict(id=i + 100, type=typ, flags=flags, name="entry-%03d" % i, data=payload)
                   for i in range(count)]
        yield name, build(entries), count, payload, typ


def hostile_fixtures():
    bomb = b"A" + b"\x90\xff" * 400
    yield "aliased-rle", vault_aliases(100, bomb, flags=1, declared_size=1)
    yield "aliased-xor-rle", vault_aliases(100, bomb, flags=3, declared_size=65535)
    yield "invalid-rle-expanded-prefix", vault_aliases(100, bomb + b"\x90", flags=1)
    yield "plain-alias-work", vault_aliases(2000, b"A" * 60000, declared_size=60000)
    yield "record-output-amplification", vault_aliases(20000, b"")


def profile():
    rows = []
    fixtures = [(n, data) for n, data, *_ in valid_fixtures()] + list(hostile_fixtures())
    for name, data in fixtures:
        elapsed, peaks = [], []
        for _ in range(3):
            tracemalloc.start()
            started = time.perf_counter()
            result = engine.salvage_bytes(data, name)
            document = result.to_dict()
            encoded = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
            elapsed.append((time.perf_counter() - started) * 1000)
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
        rows.append(dict(case=name, input_bytes=len(data), input_sha256=hashlib.sha256(data).hexdigest(),
                         format=result.format, status=result.status, records=len(result.records),
                         json_bytes=len(encoded), median_ms=round(sorted(elapsed)[1], 3),
                         peak_traced_bytes=max(peaks), damage=document["damage"]))
    return dict(schema_version=1, python=platform.python_version(), platform=platform.platform(),
                limits_source_sha256=hashlib.sha256(Path(_limits.__file__).read_bytes()).hexdigest(),
                note="Fixture construction/input allocation excluded; traced parsing plus JSON serialization included. Three runs per case; this is not process RSS.",
                rows=rows)


class VaultLargeInputs(unittest.TestCase):
    def test_valid_archives_previously_refused_are_recovered_exactly(self):
        for name, data, count, payload, typ in valid_fixtures():
            with self.subTest(case=name):
                if name.startswith("large-"):
                    self.assertGreater(len(data), _limits.MAX_LEGACY_INPUT_BYTES)
                result = engine.salvage_bytes(data, name)
                doc = check_contract(self, result, len(data))
                self.assertEqual((doc["format"], doc["status"], doc["damage"]), ("VAULT", "ok", []))
                self.assertEqual(len(doc["records"]), count)
                for index, record in enumerate(doc["records"]):
                    self.assertEqual((record["id"], record["name"], record["size"]),
                                     (index + 100, "entry-%03d" % index, len(payload)))
                    self.assertEqual(record["sha256"], hashlib.sha256(payload).hexdigest())
                    self.assertNotIn("verified", record)
                    if typ == 1:
                        self.assertEqual(record["text"], payload.decode("ascii"))
                repeated = engine.salvage_bytes(data, name).to_dict()
                self.assertEqual(json.dumps(doc, sort_keys=True), json.dumps(repeated, sort_keys=True))

    def test_hostile_inputs_are_refused_before_payload_decoding(self):
        for name, data in hostile_fixtures():
            with self.subTest(case=name), patch.object(vault, "_decode_payload") as decode:
                result = engine.salvage_bytes(data, name)
                decode.assert_not_called()
                self.assertEqual((result.format, result.status, result.records), ("VAULT", "failed", []))
                self.assertEqual([d["kind"] for d in result.damage], ["bad_length"])
                self.assertTrue(result.damage[0]["lossy"])
                self.assertEqual(result.to_dict()["damage"][0]["offset"], 0)
                self.assertIn("budget", result.notes[0])

    def test_aliases_are_charged_per_reference_and_budget_is_inclusive(self):
        data = vault_aliases(3, b"A" * 100, declared_size=100)
        # Text also reserves a failed UTF-8 attempt and fallback = 5 * payload.
        with patch.object(_limits, "MAX_VAULT_WORK_BYTES", 1500):
            self.assertIsNone(_limits.resource_issue(data, "VAULT"))
        with patch.object(_limits, "MAX_VAULT_WORK_BYTES", 1499):
            self.assertIn("payload work", _limits.resource_issue(data, "VAULT"))

    def test_output_budget_counts_only_materialized_text_and_fixed_record_cost(self):
        payload = b"A" * 100
        text = build([dict(id=1, type=1, flags=0, name="n", data=payload)])
        binary = build([dict(id=1, type=3, flags=0, name="n", data=payload)])
        with patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", _limits.VAULT_ENTRY_OUTPUT_CHARGE):
            self.assertIsNone(_limits.resource_issue(binary, "VAULT"))
            self.assertIn("output", _limits.resource_issue(text, "VAULT"))
        with patch.object(_limits, "MAX_VAULT_OUTPUT_BYTES", _limits.VAULT_ENTRY_OUTPUT_CHARGE + 400):
            self.assertIsNone(_limits.resource_issue(text, "VAULT"))

    def test_declared_size_is_not_an_expansion_bound(self):
        for size in (0, 1, 65535):
            for flags in (1, 3):
                data = vault_aliases(100, b"A" + b"\x90\xff" * 400, flags, size)
                self.assertIn("payload work", _limits.resource_issue(data, "VAULT"))

    def test_huge_declaration_cannot_create_missing_index_entries(self):
        data = struct.pack("<4sHBBII", b"VLT1", 65535, 0, 0, 16, 16)
        with patch.object(vault, "_decode_payload") as decode:
            result = engine.salvage_bytes(data, "empty-index")
        decode.assert_not_called()
        self.assertEqual((result.format, result.status, result.records), ("VAULT", "failed", []))
        self.assertIn("count_mismatch", [d["kind"] for d in result.damage])

    def test_rle_projection_matches_independent_sizes_without_allocating_output(self):
        vectors = ((b"", 0, True), (b"A\x90\xff", 255, True), (b"\x90\x00", 1, True),
                   (b"A\x90\x01", 1, True), (b"A\x90", 1, False), (b"\x90\x02", 0, False))
        for raw, size, valid in vectors:
            for key in (None, 0, 33, 255):
                stored = raw if key is None else bytes(b ^ ((key + i) & 255) for i, b in enumerate(raw))
                with self.subTest(raw=raw, key=key):
                    self.assertEqual(_limits._vault_rle_projection(stored, 0, len(stored), key), (size, valid))

    def test_plain_blocks_do_not_need_a_payload_scan_during_preflight(self):
        _, data, *_ = next(valid_fixtures())
        with patch.object(_limits, "_vault_rle_projection", side_effect=AssertionError("scanned plain bytes")):
            self.assertIsNone(_limits.resource_issue(data, "VAULT"))

    def test_expansion_scan_stops_when_cumulative_work_budget_is_exhausted(self):
        class CountedBytes(bytes):
            reads = 0
            max_slice = 0

            def __getitem__(self, key):
                result = super().__getitem__(key)
                if isinstance(key, int):
                    self.reads += 1
                else:
                    self.max_slice = max(self.max_slice, len(result))
                return result

        data = CountedBytes(vault_aliases(80, b"AB" * 600, flags=1, declared_size=1200))
        with patch.object(_limits, "MAX_VAULT_WORK_BYTES", 8000):
            self.assertIn("payload work", _limits.resource_issue(data, "VAULT"))
        # One 1,200-byte candidate is enough to exhaust this budget. Remaining
        # alias payloads are not scanned; no selected payload/output is copied.
        self.assertLessEqual(data.reads, 1200 + 16)
        self.assertLessEqual(data.max_slice, 2)


if __name__ == "__main__":
    if sys.argv[1:] == ["--profile"]:
        print(json.dumps(profile(), indent=2, sort_keys=True))
    else:
        unittest.main()
