# AGENTS.md (read first)

Project: DeadBits / PS 02 Salvage - offline CLI `./salvage <input_dir> <output_dir>` that decodes damaged
legacy binary files and reports honestly what was lost.

**Read `PROJECT-HANDOFF.txt` completely before changing anything.** It contains the output contract,
current state, ownership map, per-member task lists, workflow and rules.

Hard rules:
- Python standard library only; no network, no LLM calls at runtime.
- Edit only the files your branch owns (see section 4 of PROJECT-HANDOFF.txt). Shared files
  (`deadbits/model.py`, `engine.py`, `cli.py`, `tests/helpers.py`) are changed only by the integrator (M3).
- Never change the output contract (key names, statuses, damage kinds, file naming).
- Never invent data; unverified values carry `verified: false` / `issues`. Decoders must never raise.
- `samples/official/` is read-only.
- Before every commit: `python -m unittest discover -s tests -p "test_*.py"` and
  `python tools/compare_expected.py` (must print 7/7) both pass.
- Work on your own branch; merge to `master` only through a reviewed pull request.
