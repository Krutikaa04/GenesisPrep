# DeadBits - PS 02 Salvage

Offline CLI that identifies legacy binary files from their bytes, decodes what is provably intact,
and reports what was lost. Python 3 standard library only; no network, no AI/LLM at runtime.

## Build and run
```bash
make build                               # docker build -t deadbits .   (works offline)
./salvage <input_dir> <output_dir>       # native; or: python -m deadbits.cli <input_dir> <output_dir>

docker run --rm --network none -v "$PWD/in:/in" -v "$PWD/out:/out" deadbits /in /out
```
Writes `<output_dir>/<input name>.json` for every file in `<input_dir>` (non-recursive, directories
skipped) plus `report.json`. Always exits 0; every file is handled in isolation.

## Formats
LIBRA-98, LABLOG, VAULT, WKS, WPD (incl. encrypted -> `unsupported`), BRAVO, CVT (SEQ + VLIR),
EBCDIC-DUMP, WAD, PAK. Everything else is `UNKNOWN` / `unrecognized`. Layouts, evidence and
assumptions: [FORMAT-SPEC.md](FORMAT-SPEC.md); what was tried (incl. failures): [FIELD-LOG.md](FIELD-LOG.md).

## Tests
```bash
make test         # reference outputs, mutation hardening (truncate/flip/zero/junk every sample), CLI contract
make reference    # our output vs the organizers' 7 reference files, with their matching rules
```
The mutation suite requires: no decoder exception, only contract values (status, damage kinds), bounded
runtime, and no verified LIBRA/LABLOG record that is not in the original file.

## Honest limits
* PAK, WAD, WKS, VAULT, CVT, EBCDIC, WPD and BRAVO have no checksums: in-bounds value corruption cannot
  be detected there (`verified` only means the structure is consistent).
* Assumptions with no reference output (LIBRA flag bits 1-2, WPD soft hyphen, BRAVO paragraph rules,
  CVT VLIR text) are listed in FORMAT-SPEC.md.
