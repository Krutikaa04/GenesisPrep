"""Offline benchmark evidence backed by the source kit's existing evaluator.

Scoring remains owned by tools/evaluate.py. This adapter collects provenance,
assessment denominators and portable artifacts without changing that algorithm.
"""
import argparse
from collections import defaultdict, deque
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import threading

from deadbits.engine import salvage_bytes
from deadbits.validation.model import (
    Artifact, BenchmarkEvidence, Context, Dataset, Environment, Ratio,
    Resource, ValidationEvidence,
)
from deadbits.version import VERSION


_IMPORT_LOCK = threading.RLock()
_ARTIFACTS = (("case_ledger", "cases.json"), ("benchmark_summary", "summary.json"),
              ("dataset_manifest", "dataset.json"))


def _application_commit():
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return None
    try:
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], check=True,
                                  capture_output=True, text=True, timeout=3).stdout.strip()
        return None if git("status", "--porcelain") else git("rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return None


def _load_scorer(source_dir):
    """Load the selected tools together, restoring their legacy import effects."""
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    with _IMPORT_LOCK:
        old_path = sys.path[:]
        previous = sys.modules.get("make_variants")
        try:
            sys.modules["make_variants"] = load("make_variants", source_dir / "tools/make_variants.py")
            return load("_deadbits_benchmark_evaluator", source_dir / "tools/evaluate.py")
        finally:
            sys.path[:] = old_path
            if previous is None:
                sys.modules.pop("make_variants", None)
            else:
                sys.modules["make_variants"] = previous


def _assessment_counts(actual, baseline, counts, scorer):
    """Ask the SAME comparator which outputs are assessed; never rematch keys.

    Matching in compare_records is greedy in output order. For any prefix,
    recovered + unexpected counts precisely its assessed outputs. Appending one
    output cannot change earlier matches, so a prefix difference classifies it,
    including duplicate keys and optional records. Fully assessed output is a
    common linear fast path. Mixed partial baselines may need quadratic probes.
    """
    records = actual.get("records", [])
    assessed = counts["recovered_records"] + counts["unexpected_records"]
    verified = [scorer.is_verified(record) for record in records]
    if assessed == len(records):
        return assessed, sum(verified)
    # Probe the smaller partition and infer its complement from the total.
    probe_verified = sum(verified) <= len(records) - sum(verified)
    prefix_counts = {0: 0, len(records): assessed}

    def prefix(size):
        if size not in prefix_counts:
            result = scorer.compare_records(dict(actual, records=records[:size]), baseline)
            prefix_counts[size] = result["recovered_records"] + result["unexpected_records"]
        return prefix_counts[size]

    selected = sum(prefix(i + 1) - prefix(i) for i, flag in enumerate(verified)
                   if flag == probe_verified)
    return assessed, selected if probe_verified else assessed - selected


def _manifest(source, samples, expected, corpus):
    entries = []
    def include(label, paths):
        for path in paths:
            entries.append(dict(path=label + "/" + path.name,
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    include("scoring", [source / "tools/evaluate.py", source / "tools/make_variants.py"])
    include("samples", [p for p in samples.iterdir() if p.is_file() and not p.is_symlink()])
    include("expected", expected.glob("*.json"))
    if corpus is not None:
        include("corpus", [p for p in corpus.iterdir() if p.is_file()])
    entries.sort(key=lambda item: item["path"])
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return entries, hashlib.sha256(payload).hexdigest()


def _write_json(path, document):
    # Exclusive creation prevents clobbering an earlier run or following a link.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def run_benchmark(*, samples_dir=None, expected_dir=None, corpus_dir=None,
                  source_dir=None, output_dir=None, decoder=salvage_bytes, commit=None):
    """Return ValidationEvidence and optionally persist three audit artifacts.

    Missing explicit resources stay unavailable. An empty reference directory is
    an explicit regression-only run, never independent organizer accuracy.
    Source tools are required; portable apps can select a trusted source kit.
    """
    source = Path(source_dir).resolve() if source_dir is not None else Path(__file__).resolve().parents[2]
    samples = Path(samples_dir).resolve() if samples_dir is not None else None
    expected = Path(expected_dir).resolve() if expected_dir is not None else None
    corpus = Path(corpus_dir).resolve() if corpus_dir is not None else None
    destination = Path(output_dir).resolve() if output_dir is not None else None
    if destination is not None:
        for root in (source, samples, expected, corpus):
            if root is not None and (destination == root or root in destination.parents or destination in root.parents):
                raise ValueError("benchmark output must be separate from source, samples, references and corpus")
        destination.mkdir(parents=True, exist_ok=True)
        if any((destination / name).exists() or (destination / name).is_symlink()
               for _, name in _ARTIFACTS):
            raise ValueError("benchmark artifacts already exist; use a fresh output directory")
    resources = [
        Resource("scoring source kit", all((source / "tools" / name).is_file()
                 for name in ("evaluate.py", "make_variants.py")),
                 "Supply a trusted --source-dir containing tools/evaluate.py and tools/make_variants.py."),
        Resource("samples", samples is not None and samples.is_dir(),
                 "Explicit local samples directory required."),
        Resource("organizer reference directory", expected is not None and expected.is_dir(),
                 "Explicit reference directory required; an empty directory selects regression-only scoring."),
    ]
    if corpus is not None:
        resources.append(Resource("persisted corpus", (corpus / "manifest.json").is_file(),
                                  "Requires the existing deterministic mutation manifest and all variant files."))
    context = Context(app_version=VERSION, commit=commit if commit is not None else _application_commit(),
                      dataset=Dataset(identity=str(samples)) if samples else Dataset(),
                      environment=Environment(platform.python_version(), platform.platform()),
                      provenance="live", recorded_at=datetime.now(timezone.utc).isoformat(),
                      source=str(source))
    report, ledger, rows, manifest = None, [], [], []
    problem = None
    if all(item.available is True for item in resources):
        try:
            manifest, digest = _manifest(source, samples, expected, corpus)
            scorer = _load_scorer(source)
            captured = defaultdict(deque)
            originals = {}

            class Decoded:
                def __init__(self, doc, crashed):
                    self.doc = doc
                    self.notes = ("decoder exception",) if crashed else ()

                def to_dict(self):
                    return self.doc

            def capture(data, name):
                doc, crashed = scorer.decode(data, name, decoder)
                if name not in originals:
                    originals[name] = doc
                else:
                    captured[name].append((doc, hashlib.sha256(data).hexdigest()))
                return Decoded(doc, crashed)

            report = scorer.evaluate(samples, expected, capture, corpus)
            for case in report["cases"]:
                doc, input_hash = captured[case["source"]].popleft()
                baseline = report["baselines"][case["source"]]
                assessed, assessed_verified = _assessment_counts(doc, baseline, case, scorer)
                ledger.append(dict(case, input_sha256=input_hash, actual=doc,
                                   assessed_records=assessed, assessed_verified_records=assessed_verified))
            if _manifest(source, samples, expected, corpus) != (manifest, digest):
                raise ValueError("benchmark inputs or scoring sources changed during execution")
            context = replace(context, dataset=Dataset(identity=str(samples), sha256=digest))
            if not report["samples"]:
                resources.append(Resource("nonempty sample corpus", False, "No regular sample files were found."))
            if report["baseline_crashes"]:
                resources.append(Resource("original decoding", False,
                                          "Original decoder crashes: " + ", ".join(report["baseline_crashes"])))
            groups = defaultdict(list)
            for case in ledger:
                groups[case["baseline"], case["format"]].append(case)
            for (kind, fmt), cases in sorted(groups.items()):
                changed = [case for case in cases if case["changed_cases"]]
                totals = scorer.aggregate(changed)
                counts = dict(cases=totals["cases"], crashes=totals["crashes"])
                if kind != "no_record_baseline":
                    counts.update(expected_records=totals["expected_records"],
                                  recovered_records=totals["recovered_records"],
                                  complete_records=totals["correct_records"],
                                  wrong_records=totals["wrong_records"],
                                  false_verified_records=totals["false_verified_records"],
                                  assessed_records=sum(c["assessed_records"] for c in changed),
                                  assessed_verified_records=sum(c["assessed_verified_records"] for c in changed))
                item = BenchmarkEvidence(baseline=kind, format=fmt, context=context,
                                         resources=tuple(resources), **counts)
                rows.append(dict(evidence=item, coverage=Ratio(totals["detected_cases"], totals["detection_cases"]),
                                 unknown_retention=Ratio(totals["unknown_stayed_unknown"], totals["unknown_cases"])))
        except (OSError, ValueError, KeyError, IndexError, TypeError, ImportError,
                AttributeError, SyntaxError) as error:
            problem = "%s: %s" % (type(error).__name__, error)
            resources.append(Resource("benchmark execution", False, problem))
            rows = []
    if not rows:
        rows = [dict(evidence=BenchmarkEvidence(context=context, resources=tuple(resources)),
                     coverage=Ratio(), unknown_retention=Ratio())]
    summary = dict(schema_version=1, context=context.to_dict(), problem=problem,
                   samples=report["samples"] if report else None,
                   variants=report["variants"] if report else None,
                   changed_variants=report["changed_variants"] if report else None,
                   unchanged_variants=report["unchanged_variants"] if report else None,
                   baseline_crashes=Ratio(len(report["baseline_crashes"]), report["samples"]).to_dict() if report else Ratio().to_dict(),
                   rows=[dict(row["evidence"].to_dict(), detection_coverage=row["coverage"].to_dict(),
                              unknown_format_retention=row["unknown_retention"].to_dict()) for row in rows],
                   limitations=report["limitations"] if report else [])
    artifacts = ()
    if destination is not None:
        _write_json(destination / "cases.json", dict(schema_version=1, context=context.to_dict(),
                    baselines=report["baselines"] if report else {}, originals=originals if report else {}, cases=ledger))
        _write_json(destination / "summary.json", summary)
        _write_json(destination / "dataset.json", dict(schema_version=1, files=manifest,
                    sha256=context.dataset.sha256))
        artifacts = tuple(Artifact(role, name, hashlib.sha256((destination / name).read_bytes()).hexdigest())
                          for role, name in _ARTIFACTS)
    return ValidationEvidence(benchmarks=tuple(replace(row["evidence"], artifacts=artifacts) for row in rows))


def run(request):
    """Adapter for diagnostics.ValidationRequest and the existing --benchmark."""
    return run_benchmark(source_dir=request.source_dir, samples_dir=request.samples_dir,
                         expected_dir=request.expected_dir, corpus_dir=request.corpus_dir,
                         output_dir=request.evidence_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="trusted source kit containing existing scoring tools")
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--expected-dir", type=Path)
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    from deadbits import diagnostics, presentation
    request = diagnostics.ValidationRequest(source_dir=args.source_dir, samples_dir=args.samples_dir,
        expected_dir=args.expected_dir, corpus_dir=args.corpus_dir, evidence_dir=args.evidence_dir,
        verbose=args.verbose)
    try:
        evidence = diagnostics.run_validation("benchmark", request)
    except (OSError, ValueError) as error:
        parser.exit(1, "Benchmark error: %s\n" % error)
    presentation.emit(presentation.validation(evidence, args.verbose), sys.stdout)
    return diagnostics.exit_code(evidence)


if __name__ == "__main__":
    raise SystemExit(main())
