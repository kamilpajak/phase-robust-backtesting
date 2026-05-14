# Changelog

All notable changes to `phase-robust-backtesting` are documented here. Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.3] — 2026-05-14

### Fixed

- **G4 cost-stress no-op bug** — `audit_multi_phase._RESULT_LINE` regex now captures the optional `α-net 4F=...% t-net=...` trailing block emitted by experiment scripts since 2026-05-13. Pre-fix, the regex captured only the gross/pre-cost `t` group, and any downstream G4 cost-stress gate computed from `summarise_phase_results(...)["alpha_t"]` was a structural no-op duplicate of G1 (gross t-stat is cost-invariant by construction — `α_gross − drag_ann` only shifts `α`, not the t-stat). Material finding from AlphaLens paradigm-13 ev_fcff_yield postmortem (2026-05-13).
- **`_parse_results`** now extracts `alpha_t_net` and `alpha_net_ann` fields, with `has_net_regression: bool` flag indicating whether the values come from the genuine net-regression tokens or fall back to gross (for legacy logs).
- **`_AGGREGATED_KEYS`** in `multi_phase.summarise_phase_results` includes `alpha_t_net` so downstream consumers can compute mean/std/min/max of the net t-stat across phases.
- **`per_phase` output block** in audit_multi_phase JSON output now includes `alpha_t_net`, `alpha_net_ann`, and `has_net_regression`.

### Compatibility

Additive. Legacy experiment scripts emitting only `α 4F=...% t=...` (no `α-net 4F=...% t-net=...` trailing block) continue to parse — `alpha_t_net` falls back to `alpha_t` and `has_net_regression=False`. The pre-fix G4-as-no-op behaviour persists for those rows (consumers can detect and warn via the flag). Experiment scripts that want a genuine G4 cost-stress gate must emit the `α-net 4F=...% t-net=...` tokens.

### Tests added

- `tests/test_audit_multi_phase.py::NetRegressionParsingTests` — 4 tests covering present-tokens extraction, legacy fallback, NaN tolerance, infinity tolerance.
- `tests/test_multi_phase_aggregator.py::test_alpha_t_net_is_aggregated_for_g4_cost_stress` — verifies aggregator reports net independently of gross.

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
