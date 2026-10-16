"""The shared engine discovers adapters and isolates broken extensions."""
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import check_contract
from deadbits import engine
from deadbits.model import FORMAT_NAMES, Result


class Registry(unittest.TestCase):
    def test_all_ten_formats_discovered_without_private_modules(self):
        self.assertEqual({mod.NAME for mod in engine.ADAPTERS}, set(FORMAT_NAMES) - {"UNKNOWN"})
        self.assertTrue(all(not mod.__name__.split(".")[-1].startswith("_") for mod in engine.ADAPTERS))

    def test_drop_in_discovery_and_bad_module_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            package_dir = Path(directory) / "salvage_test_plugins"
            package_dir.mkdir()
            (package_dir / "__init__.py").write_text("")
            code = 'NAME="PAK"\ndef detect(data): return 0.9\ndef decode(data, name): return None\n'
            for name in ("zeta", "alpha"):
                (package_dir / (name + ".py")).write_text(code)
            (package_dir / "_helper.py").write_text('raise RuntimeError("must not import")')
            (package_dir / "broken.py").write_text('raise RuntimeError("broken adapter")')
            (package_dir / "incomplete.py").write_text('NAME="WAD"')
            (package_dir / "invalid.py").write_text(code.replace('"PAK"', '"NEW-CONTRACT-NAME"'))
            with patch.object(sys, "path", [directory] + sys.path):
                try:
                    package = importlib.import_module("salvage_test_plugins")
                    discovered = engine.discover_adapters(package)
                    self.assertEqual([m.__name__.split(".")[-1] for m in discovered], ["alpha", "zeta"])
                    self.assertNotIn("salvage_test_plugins._helper", sys.modules)
                finally:
                    for name in list(sys.modules):
                        if name.startswith("salvage_test_plugins"):
                            sys.modules.pop(name)

    def test_bad_scores_and_detectors_do_not_mask_valid_adapter(self):
        def broken(data):
            raise ValueError("detector error")
        def adapter(detect):
            return types.SimpleNamespace(NAME="PAK", detect=detect,
                                         decode=lambda data, name: Result(name, "PAK", "ok"))
        bad = [adapter(lambda data, value=value: value) for value in
               (float("nan"), float("inf"), -1, 10, None, "bad")]
        with patch.object(engine, "ADAPTERS", bad + [adapter(broken), adapter(lambda data: 0.9)]):
            result = engine.salvage_bytes(b"input", "test")
        self.assertEqual((result.format, result.status), ("PAK", "ok"))

    def test_broken_decoder_and_invalid_result_become_failed(self):
        def raises(data, name):
            raise ValueError("bad input")
        for decode in (raises, lambda data, name: object(), lambda data, name: Result(name, "INVALID", "ok")):
            adapter = types.SimpleNamespace(NAME="PAK", detect=lambda data: 1, decode=decode)
            with patch.object(engine, "ADAPTERS", [adapter]):
                result = engine.salvage_bytes(b"test", "test")
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.format, "PAK")
            self.assertEqual(result.to_dict()["damage"][0]["kind"], "unparsed_bytes")

    def test_empty_registry_returns_unknown(self):
        with patch.object(engine, "ADAPTERS", []):
            check_contract(self, engine.salvage_bytes(b"not an archive", "x"), 14)

    def test_invalid_result_shapes_and_identity_are_isolated(self):
        for field, value in (("records", None), ("records", ["bad"]),
                             ("metadata", []), ("damage", [None]), ("notes", "bad"),
                             ("format", "WAD"), ("source_file", "wrong")):
            with self.subTest(field=field):
                result = Result("test", "PAK", "ok")
                setattr(result, field, value)
                adapter = types.SimpleNamespace(NAME="PAK", detect=lambda data: 1,
                                                decode=lambda data, name: result)
                with patch.object(engine, "ADAPTERS", [adapter]):
                    recovered = engine.salvage_bytes(b"test", "test")
                self.assertEqual(recovered.status, "failed")
                self.assertEqual(recovered.records, [])
                recovered.to_dict()
