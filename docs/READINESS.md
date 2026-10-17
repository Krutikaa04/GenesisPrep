# Beginner onboarding and release-readiness review

This is an unpublished development candidate. Published v0.1.0 stays immutable;
the version remains 0.2.0-dev. This work prepares use and validation, not release
publication or a bundled-Python/native MSI/PKG distribution.

## First-time journey

Existing Python 3.10+ -> extract installer -> open the platform setup helper ->
choose Y to start -> numbered welcome menu -> Recover files -> Browse or paste
input -> accept a fresh results folder -> confirm -> inspect summary -> open
results. A managed Start Salvage entry allows later use without PATH setup.

The menu preserves existing output directories and input contents. Native
folder selection is optional; missing Tk/display support falls back to typed
paths. Accuracy needs independent supplied answers. Demo/test/scoring resources
are optional; the matching source archive is explicitly located by the release
manifest as the offline validation kit. Executing external source-kit code needs
an explicit trust choice in the menu. Cancellation and EOF do not fabricate a
successful recovery or validation run.

## Review gates

The canonical builder packages committed blobs twice identically, hashes the
application/source/installer and records the exact commit. The expanded release
checker verifies:

- Extracted source without Git metadata: full tests and immutable fixtures.
- Source, portable and installed recovery: byte-identical 31 JSON files on the
  30 organizer inputs, seven independent reference comparisons, strict contract.
- Beginner-menu recovery outside the checkout, Unicode/space installation paths,
  explicit kit selection, dynamic record accuracy, selected live tests, benchmark
  and guided demo services, and empty-answer refusal.
- Installation/reinstallation, legacy managed-layout upgrade, managed Start
  entry, removal preserving unrelated/user results, and clickable setup/removal
  helper bodies in a temporary user profile.
- Required modules, checksums, Python/version agreement, optional kit location,
  standard-library imports and recovery/install socket-audit checks. Trusted
  validation subprocess execution is distinct from that recovery/install guard.
- CI matrix: Linux Python 3.10/3.12/3.14, Windows/macOS Python 3.12, plus native /
  offline Docker parity. Each CI proof records actual test and skip counts.

`tools/check_release.py --dist DIST --output PROOF.json` produces the concrete
commit/hash/measurement evidence. CI downloads the same canonical artifacts on
each platform; it does not rebuild a different application per machine.

## Practical boundaries and final publication

Python is still required. Setup never downloads it, edits macOS Python, changes
shell profiles/PATH/registry, or requires administrator access. Windows helpers
use an existing registered Python launcher; installations without `py` can use
the documented direct interpreter command. Unsigned scripts, executable-bit
loss on ZIP extraction and OS trust policies can require manual opening steps.
These are not signed one-click native application installers.

Native dialog behavior and subjective ease of use are not established by
headless CI. The typed-path route is exercised end to end. The known format,
corruption-detection, resource and filesystem limits remain in README.md and
FORMAT-SPEC.md. Passing references is scoped agreement, not universal accuracy.

Before publishing: review this PR and its generated platform evidence, select
the final version explicitly, rebuild/revalidate that exact committed version,
then authorize its tag/assets. Final downloads must use the validated bytes and
checksums. No publication is implied by completion of these arrangements.
