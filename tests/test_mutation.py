"""Hardening: mutate every real sample and require graceful, honest behaviour.

For each of the 30 kit files we truncate at every offset, flip bytes, zero blocks and force header
bytes to extreme values. Required: no decoder exception, contract-valid output, bounded runtime,
and -- for the two formats with real checksums -- no verified record that is not in the original.
"""
import random
import time
import unittest

from helpers import check_contract, sample_files, salvage_bytes

CHECKSUMMED = {"LIBRA-98", "LABLOG"}


TEXT_FIELDS = {"title", "author"}   # re-decoded under the header's codepage flag, so excluded from the invariant


def record_key(r):
    return repr(sorted((k, v) for k, v in r.items() if k not in {"verified", "issues"} | TEXT_FIELDS))


class Mutation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = [(p.name, p.read_bytes()) for p in sample_files()]
        cls.originals = {}
        for name, data in cls.files:
            r = salvage_bytes(data, name)
            cls.originals[name] = (r.format, {record_key(x) for x in r.records})

    def run_mutants(self, name, data, mutants):
        fmt, orig = self.originals[name]
        for label, m in mutants:
            t0 = time.time()
            res = salvage_bytes(m, name)
            self.assertLess(time.time() - t0, 5.0, "%s %s too slow" % (name, label))
            doc = check_contract(self, res, len(m), "%s %s" % (name, label))
            if fmt in CHECKSUMMED and res.format == fmt:
                for rec in doc["records"]:
                    if rec.get("verified", True) is True and "issues" not in rec:
                        self.assertIn(record_key(rec), orig, "%s %s: verified record not in original: %r"
                                      % (name, label, rec))

    def test_truncation_at_every_offset(self):
        for name, data in self.files:
            self.run_mutants(name, data, [("cut@%d" % i, data[:i]) for i in range(len(data))])

    def test_single_byte_flips(self):
        for name, data in self.files:
            step = 1 if len(data) <= 700 else 3
            muts = []
            for i in range(0, len(data), step):
                for mask in (0x01, 0x80, 0xFF):
                    b = bytearray(data)
                    b[i] ^= mask
                    muts.append(("flip@%d^%02x" % (i, mask), bytes(b)))
            self.run_mutants(name, data, muts)

    def test_extreme_values_and_zero_blocks(self):
        rng = random.Random(1234)
        for name, data in self.files:
            muts = []
            for i in range(0, min(len(data), 64)):
                for v in (0x00, 0xFF, 0x7F):
                    b = bytearray(data)
                    b[i] = v
                    muts.append(("set@%d=%02x" % (i, v), bytes(b)))
            for _ in range(60):
                a = rng.randrange(len(data)) if data else 0
                n = rng.randint(1, 40)
                b = bytearray(data)
                b[a:a + n] = b"\x00" * len(b[a:a + n])
                muts.append(("zero@%d+%d" % (a, n), bytes(b)))
            self.run_mutants(name, data, muts)

    def test_garbage_and_appended_junk(self):
        rng = random.Random(99)
        for name, data in self.files:
            muts = [("append", data + bytes(rng.randrange(256) for _ in range(40))),
                    ("prepend", bytes(rng.randrange(256) for _ in range(8)) + data),
                    ("double", data + data)]
            self.run_mutants(name, data, muts)
        for n in (1, 2, 3, 4, 7, 15, 16, 31, 32, 255, 4096):
            check_contract(self, salvage_bytes(bytes(rng.randrange(256) for _ in range(n)), "rnd"), n, "rnd%d" % n)
            check_contract(self, salvage_bytes(b"\xff" * n, "ff"), n, "ff%d" % n)
            check_contract(self, salvage_bytes(b"\x00" * n, "zero"), n, "zero%d" % n)


if __name__ == "__main__":
    unittest.main()
