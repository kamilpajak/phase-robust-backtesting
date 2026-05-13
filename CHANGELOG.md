# Changelog

All notable changes to `phase-robust-backtesting` are documented here. Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.2] — 2026-05-13

### Added

- **`Registration.extras: dict[str, Any]` field** — accepts arbitrary top-level JSON keys that aren't declared dataclass fields. `Registration.from_dict()` auto-routes unknown keys into `extras` instead of raising `TypeError`. `Registration.to_dict()` flattens `extras` back to top-level so the on-disk JSON shape stays identical to pre-0.2.2 entries (zero git-diff churn on round-trip).
- **`Ledger.complete(outcome_extras=...)` kwarg** — merges arbitrary keys into the outcome dict alongside the canonical metrics. Use for paradigm-specific forensic data (`windows_evaluated`, `pod_compute`, `audit_orchestrator_log`, etc.) without bypassing the API via manual JSON patches.
- Collision safety: declared dataclass fields always win over extras with the same name (both on read and write). Canonical `complete()` kwargs always win over `outcome_extras` of the same name.

### Why

Downstream research projects (notably AlphaLens, the original consumer per the methodology-bundle extraction) accumulate paradigm-specific forensic data attached to ledger entries — phase-A pre-screen results, pod compute logs, postmortem links. v0.2.1's closed schema either blocked these (`TypeError` on reload) or forced manual JSON patching outside the API. The `extras` hook keeps PRB methodology-agnostic while letting downstream projects extend the ledger payload safely.

### Compatibility

Additive only. All 0.2.1 callers continue to work without changes. JSON shape is preserved (`extras` is a serialised flat at top level, not a wrapper).

## [0.2.1] — earlier

- Bug fix: unlink transient `/tmp` audit reports after parsing (memory hygiene under long ThreadPoolExecutor sweeps).

## [0.2.0] — earlier

- Dispersion gate, UTF-8 ledger I/O, `run_audit()` entry point.

## [0.1.0] — initial extraction from AlphaLens

- Pre-registration ledger, multi-phase audit driver, Bonferroni thresholds.
