"""Versioned runner/presenter interface; no filesystem or process side effects.

See docs/VALIDATION-EVIDENCE.md for denominators and baseline limitations.
Unknown measurements are None; a measured zero is explicitly 0.
"""
from dataclasses import dataclass, fields
from typing import Optional, Protocol, Tuple


SCHEMA_VERSION = 1
BASELINES = ("organizer_reference", "regression_baseline", "no_record_baseline")


def _count(name, value):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(name + " must be a nonnegative integer or None")


def _text(name, value):
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(name + " must be a nonempty string or None")


def _bounded(name, numerator, denominator):
    if numerator is not None and denominator is not None and numerator > denominator:
        raise ValueError(name + " exceeds its denominator")


class _Model:
    def to_dict(self):
        """Return fresh JSON-compatible data, including derived measurements."""
        def encode(value):
            if isinstance(value, _Model):
                return value.to_dict()
            if isinstance(value, tuple):
                return [encode(item) for item in value]
            return value
        return {field.name: encode(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class Ratio(_Model):
    numerator: Optional[int] = None
    denominator: Optional[int] = None

    def __post_init__(self):
        _count("numerator", self.numerator)
        _count("denominator", self.denominator)
        _bounded("numerator", self.numerator, self.denominator)

    @property
    def value(self):
        if self.numerator is None or not self.denominator:
            return None
        return self.numerator / self.denominator

    def to_dict(self):
        return dict(super().to_dict(), value=self.value)


@dataclass(frozen=True)
class Dataset(_Model):
    identity: Optional[str] = None
    sha256: Optional[str] = None

    def __post_init__(self):
        _text("identity", self.identity)
        if self.sha256 is not None and (not isinstance(self.sha256, str) or
                len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters or None")


@dataclass(frozen=True)
class Environment(_Model):
    python_version: Optional[str] = None
    platform: Optional[str] = None

    def __post_init__(self):
        for field in fields(self):
            _text(field.name, getattr(self, field.name))


@dataclass(frozen=True)
class Context(_Model):
    app_version: Optional[str] = None
    commit: Optional[str] = None
    dataset: Dataset = Dataset()
    environment: Environment = Environment()
    provenance: str = "unknown"
    recorded_at: Optional[str] = None
    source: Optional[str] = None

    def __post_init__(self):
        if self.provenance not in ("live", "historical", "unknown"):
            raise ValueError("invalid provenance")
        for name in ("app_version", "commit", "recorded_at", "source"):
            _text(name, getattr(self, name))
        if not isinstance(self.dataset, Dataset) or not isinstance(self.environment, Environment):
            raise ValueError("context requires Dataset and Environment objects")


@dataclass(frozen=True)
class Resource(_Model):
    name: str
    available: Optional[bool] = None
    detail: Optional[str] = None

    def __post_init__(self):
        _text("name", self.name)
        if self.name is None:
            raise ValueError("resource name is required")
        if self.available is not None and type(self.available) is not bool:
            raise ValueError("available must be bool or None")
        _text("detail", self.detail)


@dataclass(frozen=True)
class Artifact(_Model):
    """A saved actual output, expected input, comparison, or case ledger."""
    role: str
    path: str
    sha256: Optional[str] = None

    def __post_init__(self):
        for name in ("role", "path"):
            _text(name, getattr(self, name))
            if getattr(self, name) is None:
                raise ValueError(name + " is required")
        Dataset(sha256=self.sha256)


@dataclass(frozen=True)
class _Section(_Model):
    context: Context = Context()
    resources: Tuple[Resource, ...] = ()
    artifacts: Tuple[Artifact, ...] = ()

    def __post_init__(self):
        if not isinstance(self.context, Context):
            raise ValueError("section context must be a Context")
        for name, kind in (("resources", Resource), ("artifacts", Artifact)):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(item, kind) for item in value):
                raise ValueError(name + " must be a tuple of " + kind.__name__)

    @property
    def resources_available(self):
        return all(resource.available is True for resource in self.resources)

    def to_dict(self):
        return dict(super().to_dict(), status=self.status)


@dataclass(frozen=True)
class RecordAccuracy(_Model):
    """Counts against supplied answers, excluding optional partial identities."""
    expected: int = 0
    recovered: int = 0
    correct: int = 0
    wrong: int = 0
    missing: int = 0
    unexpected: int = 0
    optional: int = 0

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            _count(field.name, value)
            if value is None:
                raise ValueError('record counts must be measured integers')
        if self.correct + self.wrong != self.recovered or self.recovered + self.missing != self.expected:
            raise ValueError('record counts do not reconcile')

    @property
    def measurements(self):
        return dict(recovery=Ratio(self.recovered, self.expected),
                    accuracy=Ratio(self.correct, self.expected),
                    precision=Ratio(self.correct, self.recovered + self.unexpected))

    def to_dict(self):
        return dict(super().to_dict(), measurements={k: v.to_dict() for k, v in self.measurements.items()})


@dataclass(frozen=True)
class ReferenceEvidence(_Section):
    matched: Optional[int] = None
    total: Optional[int] = None
    record_accuracy: Optional[RecordAccuracy] = None
    record_accuracy_detail: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()
        Ratio(self.matched, self.total)
        if self.record_accuracy is not None and not isinstance(self.record_accuracy, RecordAccuracy):
            raise ValueError('record_accuracy must be RecordAccuracy or None')
        _text('record_accuracy_detail', self.record_accuracy_detail)

    @property
    def agreement(self):
        return Ratio(self.matched, self.total)

    @property
    def status(self):
        if not self.resources_available or self.agreement.value is None:
            return "unavailable"
        return "passed" if self.matched == self.total else "failed"

    def to_dict(self):
        return dict(super().to_dict(), agreement=self.agreement.to_dict())


@dataclass(frozen=True)
class TestEvidence(_Section):
    passed: Optional[int] = None
    failed: Optional[int] = None
    errors: Optional[int] = None
    skipped: Optional[int] = None
    expected_failures: Optional[int] = None
    unexpected_successes: Optional[int] = None

    def __post_init__(self):
        super().__post_init__()
        for name in self._outcomes:
            _count(name, getattr(self, name))

    _outcomes = ("passed", "failed", "errors", "skipped", "expected_failures", "unexpected_successes")

    @property
    def total(self):
        values = [getattr(self, name) for name in self._outcomes]
        return None if None in values else sum(values)

    @property
    def success(self):
        # Skips/expected failures are explicit outcomes, never ordinary passes.
        return Ratio(self.passed, self.total)

    @property
    def status(self):
        if not self.resources_available:
            return "unavailable"
        if any((getattr(self, name) or 0) > 0 for name in ("failed", "errors", "unexpected_successes")):
            return "failed"
        if self.total is None or self.total == self.skipped:
            return "unavailable"
        return "passed"

    def to_dict(self):
        return dict(super().to_dict(), total=self.total, success=self.success.to_dict())


@dataclass(frozen=True)
class BenchmarkEvidence(_Section):
    baseline: str = "no_record_baseline"
    format: Optional[str] = None
    cases: Optional[int] = None
    crashes: Optional[int] = None
    expected_records: Optional[int] = None
    recovered_records: Optional[int] = None
    complete_records: Optional[int] = None
    assessed_records: Optional[int] = None
    assessed_verified_records: Optional[int] = None
    wrong_records: Optional[int] = None
    false_verified_records: Optional[int] = None

    def __post_init__(self):
        super().__post_init__()
        if self.baseline not in BASELINES:
            raise ValueError("unknown baseline; mixed baselines are not supported")
        _text("format", self.format)
        for name in self._counts:
            _count(name, getattr(self, name))
        for numerator, denominator in (("crashes", "cases"),
                ("recovered_records", "expected_records"),
                ("complete_records", "recovered_records"),
                ("complete_records", "expected_records"),
                ("recovered_records", "assessed_records"),
                ("assessed_verified_records", "assessed_records"),
                ("wrong_records", "assessed_records"),
                ("false_verified_records", "wrong_records"),
                ("false_verified_records", "assessed_verified_records")):
            _bounded(numerator, getattr(self, numerator), getattr(self, denominator))
        if self.baseline == "no_record_baseline" and any(
                getattr(self, name) is not None for name in self._counts[2:]):
            raise ValueError("no record baseline: record measurements must remain unknown")

    _counts = ("cases", "crashes", "expected_records", "recovered_records", "complete_records",
               "assessed_records", "assessed_verified_records", "wrong_records", "false_verified_records")

    @property
    def measurements(self):
        return {
            "recovery": Ratio(self.recovered_records, self.expected_records),
            "completeness": Ratio(self.complete_records, self.expected_records),
            "wrong": Ratio(self.wrong_records, self.assessed_records),
            "false_verified": Ratio(self.false_verified_records, self.assessed_verified_records),
            "crashes": Ratio(self.crashes, self.cases),
        }

    @property
    def status(self):
        if not self.resources_available or not self.cases or self.crashes is None:
            return "unavailable"
        return "failed" if self.crashes else "measured"

    def to_dict(self):
        return dict(super().to_dict(), measurements={k: v.to_dict() for k, v in self.measurements.items()})


@dataclass(frozen=True)
class ValidationEvidence(_Model):
    """One run; absent sections stay null and benchmarks never mix baselines."""
    reference: Optional[ReferenceEvidence] = None
    tests: Optional[TestEvidence] = None
    benchmarks: Tuple[BenchmarkEvidence, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported validation evidence schema version")
        for name, kind in (("reference", ReferenceEvidence), ("tests", TestEvidence)):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), kind):
                raise ValueError(name + " has the wrong evidence type")
        if not isinstance(self.benchmarks, tuple) or any(
                not isinstance(item, BenchmarkEvidence) for item in self.benchmarks):
            raise ValueError("benchmarks must be a tuple of BenchmarkEvidence")

    @property
    def status(self):
        sections = tuple(s for s in (self.reference, self.tests) if s is not None) + self.benchmarks
        if not sections:
            return "unavailable"
        if any(s.status == "failed" for s in sections):
            return "failed"
        if any(s.status == "unavailable" for s in sections):
            return "unavailable"
        # Completion is not a claim of 100% recovery, or of independent accuracy.
        return "complete"

    def to_dict(self):
        return dict(super().to_dict(), status=self.status)

    @classmethod
    def from_dict(cls, document):
        """Load saved evidence; reject unknown schema/fields and stale derived data.

        Derived keys may be omitted, but supplied statuses/rates must match the
        counts. Historical importers must explicitly supply historical contexts;
        loading does not relabel an earlier live measurement as a new live run.
        """
        def restore(kind, data, nested=None):
            if not isinstance(data, dict):
                raise ValueError(kind.__name__ + " must be an object")
            values = {field.name: data[field.name] for field in fields(kind) if field.name in data}
            for name, (child, sequence) in (nested or {}).items():
                if name not in values or values[name] is None:
                    continue
                if sequence:
                    if not isinstance(values[name], list):
                        raise ValueError(name + " must be an array")
                    values[name] = tuple(load(child, item) for item in values[name])
                else:
                    values[name] = load(child, values[name])
            result = kind(**values)
            canonical = result.to_dict()
            for key, value in data.items():
                if key not in canonical or (key not in values and value != canonical[key]):
                    raise ValueError("unknown or inconsistent evidence field: " + key)
            return result

        def load(kind, data):
            if kind is cls:
                nested = {"reference": (ReferenceEvidence, False), "tests": (TestEvidence, False),
                          "benchmarks": (BenchmarkEvidence, True)}
            elif kind is Context:
                nested = {"dataset": (Dataset, False), "environment": (Environment, False)}
            elif issubclass(kind, _Section):
                nested = {"context": (Context, False), "resources": (Resource, True),
                          "artifacts": (Artifact, True)}
                if kind is ReferenceEvidence:
                    nested['record_accuracy'] = (RecordAccuracy, False)
            else:
                nested = {}
            return restore(kind, data, nested)

        if not isinstance(document, dict) or "schema_version" not in document:
            raise ValueError("saved evidence requires schema_version")
        return load(cls, document)


class Runner(Protocol):
    def __call__(self) -> ValidationEvidence:
        """Measure a requested scope, preserving unknown/missing information."""
        ...


class Presenter(Protocol):
    def __call__(self, evidence: ValidationEvidence) -> str:
        """Render counts, denominators, baseline labels and provenance honestly."""
        ...
