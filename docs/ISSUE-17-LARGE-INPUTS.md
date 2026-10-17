# Issue 17: selective large-input support

VAULT's measured alias/expansion policy is documented in VAULT-LARGE-FILES.md.
The remaining formats are reviewed separately: CVT, LIBRA-98, LABLOG, WKS and
EBCDIC-DUMP. Each per-format PR adds its own private preflight module, independent
fixtures, measured before/after ledger and limits documentation. The shared
enabling commit is identical across those PRs; merging it once suffices.

The public engine retains its 128MiB reader ceiling. Existing small-input and
damaged-input policies stay in force. Only an input that would otherwise be
refused reaches the selective preflight. It must fit an **8MiB scan ceiling**,
**32MiB logical work budget**, **16MiB logical output budget**, and **100,000
physical-item budget**, all inclusive. Individual helpers impose additional
framing constraints and conservative charges described in their own documents.

These are logical work/output units, not process RSS, exact Python allocation
or serialized JSON sizes. Input storage, object overhead and JSON escaping add
memory. Timings and traced allocations are observations on the recorded machine,
not cross-platform time guarantees. Profiling excludes fixture construction and
already allocated inputs, and includes parsing and JSON serialization.

Missing helpers, import failures, failed checks and invalid helper results keep
the original refusal. Helpers are explicitly named trusted local modules, not
runtime input plugins. A rejected file remains recognized/failed with no records
and a lossy bad_length at offset zero. Preflight never clips input or manufactures
a complete-looking prefix. Direct internal decoder calls bypass engine preflight;
the supported safety boundary is salvage_bytes/salvage_file/the CLI.

Files with unsupported framing can still be refused even if they would happen
to be affordable. This issue selectively admits demonstrated legitimate cases;
it does not promise arbitrary large damaged-file recovery or a streaming reader.
VAULT aliases and decompression amplification retain their separate tested
budgets. Other formats' selected ranges and item counts are charged from physical
bytes, not allocation-sized header declarations.

Issue 19 packaging/demo/readiness work and release publication are outside scope.
