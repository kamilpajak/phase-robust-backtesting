# Methodology templates

Five operational templates extracted from the AlphaLens 2026-04-29 → 2026-05-01 sessions. Each is a small, self-contained pattern that addresses a specific failure mode catalogued in [`anti_patterns.md`](anti_patterns.md). They are not part of the core toolkit code (which intentionally stays minimal at ~400 LOC) — they are reference implementations you copy into your own backtest harness.

---

## 1. Adversarial review pipeline (zen + perplexity)

**Use when:** Drafting any new pre-registered design, especially if the design is post-hoc motivated by a prior FAIL on the same holdout (= HARKing-vulnerable per [Mechanism #3](anti_patterns.md#3-multiple-testing-inflation-max-of-n-selection-bias)).

**Pattern:**

1. Write a design memo (`docs/research/<id>_design_<date>.md`) covering: hypothesis (H₁ + H₀), variables changed vs prior, threshold (in-class + program-level + Romano-Wolf), HARKing acknowledgment, open risks for review.
2. Run **two independent adversarial reviewers in parallel**, both seeded with the same memo + project context:
   - **Methodology reviewer** (e.g., Gemini 3 Pro) — challenges study design, math, reasoning.
   - **Literature reviewer** (e.g., Perplexity Reason / web-grounded) — checks against published literature, cites methodology papers (Kerr 1998, Simmons et al. 2011, Bailey et al. 2014, Romano-Wolf 2005).
3. Synthesize findings; tag each objection 1-3 stars by severity. **REJECT** spec if any reviewer scores fatal (★★★) on a math or HARKing issue.
4. Revise the memo, re-mark `Status:` from DRAFT to LOCKED.
5. Lock the pre-reg JSON via the `ledger` toolkit BEFORE running Phase B compute.

**Concrete impact (AlphaLens 2026-05-01 sessions):** Adversarial review caught **fatal flaws on 4 design specs** before compute:
- v8 LightGBM-quantile (zen ★★★): quantile loss in LightGBM hardcodes hessian=1.0, making trees tail-blind.
- v10 analyst features original spec (zen + perplexity ★★★): yfinance survivorship not addressed in design.
- v6a original (mega-cap exclusion vs SPY benchmark, zen ★★★): comparing non-mega-cap subset against SPY in mega-cap rally is mathematically self-defeating (structural −35% gap before any α test).
- v6c continuous-weighting (zen ★★★): IC×breadth ceiling math (#5 below) showed Phase B was pre-doomed.

Estimated saved compute: ~10-15h across the 4 catches.

---

## 2. Survivorship probe (delisted-ticker retention gate)

**Use when:** Adopting a new data provider for any feature whose historical retention for delisted tickers is not explicitly documented and independently verified. Critical for analyst events, news, fundamentals, options, alt-data — any source where the vendor may have pruned post-delisting records.

**Pattern (verbatim from AlphaLens v10 implementation):**

```python
# scripts/probe_<provider>_<feature>_survivorship.py

def main():
    # 1. Sample n=200 known-delisted tickers from a pre-2 year delisting window
    #    (give each ticker ≥1y of pre-delisting coverage opportunity).
    delisted = sample_delisted(n=200, window=("2018-01-01", "2024-04-30"))

    # 2. Sample n=200 active tickers from your current PIT universe.
    active = sample_active(n=200, pit_window=("2023-01-01", "2024-04-30"))

    # 3. For each ticker, query the provider's feature endpoint; record
    #    (event_count, status) where status ∈ {ok, empty, error}.
    delisted_counts = [probe_provider(t) for t in delisted]
    active_counts = [probe_provider(t) for t in active]

    # 4. Bootstrap z-test on event-rate ratio under H₀: ratio = 1.0.
    point_ratio, z, p = bootstrap_ratio_z(delisted_counts, active_counts)

    # 5. FAIL gate (locked pre-run, no tuning):
    fail = (point_ratio < 0.5) and (z > 2.0)

    # 6. Pre-registered auto-pivot trigger:
    if fail:
        return pivot_to_alternative_hypothesis()  # see template #3
```

**Empirical anchor:** yfinance `upgrades_downgrades` failed catastrophically on this probe — delisted/active ratio = 0.003, z = 620, p < 0.0001. Probe took 5 minutes to run; saved ~2-3 weeks of work that would have been spent on a backtest with systematic look-ahead leak.

**Default thresholds (locked pre-reg):** ratio_fail < 0.5 AND z > 2.0. Both conditions required (avoids triggering on tiny samples or noisy ratios).

---

## 3. Pre-registered auto-pivot trigger (HARKing prevention)

**Use when:** A pre-Phase-B gate (e.g., survivorship probe, in-CV IR sanity, multicollinearity) might fail and you want to switch to an alternative hypothesis without it being post-hoc HARKing.

**Pattern:**

In the pre-reg JSON, add a `phase_a_gates` block AND a `<alternative>_auto_pivot_reservation` block. Specify the trigger condition objectively (numeric thresholds, no experimenter discretion at decision time):

```jsonc
{
  "phase_a_gates": {
    "gate_2_survivorship_hard_block": {
      "trigger": "probe upgrades_downgrades for full delisted set",
      "fail_condition": "delisted/active event-rate ratio < 0.5 with z > 2",
      "fail_action": "AUTO-PIVOT to Path β (long-only top-decile, n=5 in-class)",
      "rationale": "objective trigger eliminates experimenter discretion at decision time"
    }
  },
  "path_beta_auto_pivot_reservation": {
    "trigger": "Phase A gate 2 FAIL on full delisted-ticker probe",
    "objective_condition": "delisted_active_event_rate_ratio < 0.5 with z > 2",
    "scope_if_triggered": "long-only top-decile in <existing class>",
    "in_class_n_if_triggered": 5,
    "in_class_threshold_if_triggered": "|t|>=2.58",
    "harking_flag_if_triggered": "Path β was post-hoc designed against observed v4 long-leg performance; trigger eliminates post-hoc switch HARKing but design itself remains conditional"
  }
}
```

**Why this works:** the alternative hypothesis is registered BEFORE seeing the gate result; the trigger condition is numeric-only. Switching from primary to alternative is mechanical, not discretionary, so it doesn't add a degree of freedom. The alternative still inherits its own multiplicity penalty (in-class + program-level Bonferroni), but the swap isn't an additional test.

**Empirical anchor:** AlphaLens v10 → v5 auto-pivot fired in ~5 minutes (probe time). Without pre-registration, the decision to "switch to long-only after seeing yfinance fail" would have been classical hypothesis-mining (Kerr 1998).

---

## 4. Feature parquet cache with input-only key

**Use when:** Iterating multiple selection-rule / model-class / threshold variants on identical features. A 50-min feature joiner build per iteration is wasteful when the actual experiment is <5 min once features are loaded.

**Pattern:**

```python
import hashlib
from pathlib import Path

cache_dir = Path.home() / ".alphalens" / "feature_cache"
cache_dir.mkdir(parents=True, exist_ok=True)

# CRITICAL: cache key on INPUT params only, NOT on realized calendar.
# Realized calendar drifts day-to-day as price data refreshes; including it
# would invalidate the cache between sessions even when inputs are unchanged.
cache_key_payload = (
    ",".join(sorted(universe))
    + f"|train_start={args.train_start.isoformat()}"
    + f"|holdout_start={args.holdout_start.isoformat()}"
    + f"|holdout_end={args.holdout_end.isoformat()}"
    + f"|stride={args.rebalance_stride}"
    + f"|holding={args.holding}"
    + "|features_v=v3_v4_v5_10feat"  # bump on features.py contract change
)
cache_key = hashlib.sha256(cache_key_payload.encode()).hexdigest()[:16]
cache_path = cache_dir / f"features_{cache_key}.parquet"

if cache_path.exists() and not args.force_rebuild_features:
    features = pd.read_parquet(cache_path)
else:
    features = build_feature_frame(...)  # 50-min compute
    features.to_parquet(cache_path, index=False)
```

**Anti-patterns to avoid:**
- ❌ Including realized `asof_dates` in the key — drifts with data refresh.
- ❌ Including the benchmark in the key when features don't depend on it.
- ❌ Using a wall-clock timestamp as cache key — never hits.
- ❌ Saving to repo (use `~/.alphalens/feature_cache/` outside git, like Lean OHLCV cache).

**Add a `features_v` version string** to the key. Bump it on any `build_feature_frame` contract change. Old cache files become orphans you can manually delete.

**Empirical impact:** AlphaLens v6a-revised re-run loaded cached features in **24ms** vs ~50min build (12,500× speedup). Allowed ~5min iteration cycles for selection-rule variants until [Mechanism #9](anti_patterns.md#9-data-provider-survivorship-broken-delisted-retention) ceiling math closed cache-enabled exploration.

---

## 5. IC × breadth ceiling — pre-run feasibility test

**Use when:** Before running Phase B for any selection-rule or portfolio-construction variant on a feature stack with known bulk rank-IC. Especially critical when adversarial review needs a hard yes/no on "is this experiment mathematically reachable at the locked threshold?"

**Pattern:**

The Grinold (1989) Fundamental Law of Active Management gives the upper bound on Sharpe ratio for an information-coefficient-driven strategy:

```
IR_max ≈ IC × √breadth
Sharpe_max ≈ IR_max  (if returns are roughly uncorrelated; tighter bound: IR × σ_excess / σ_residual)
```

For a 2-year holdout with N effective independent rebalances, the t-stat ceiling under iid assumption is:

```
t_stat_max ≈ Sharpe_max × √(N_eff / years_per_year_factor)
           ≈ IC × √(N_eff)
```

**Worked example (AlphaLens v6c continuous-weighted, REJECTED-PRE-RUN):**

- Bulk holdout rank-IC measured on v3-v6a: **0.024**
- 2-year holdout, ~50 rebal/year × 2y = 100 raw rebalances, **75% overlap → N_eff ≈ 25-40**
- Theoretical max t-stat: `0.024 × √(35) ≈ 0.142 × √(years/overlap) ≈ 0.48`
- Locked pre-reg threshold: |t| ≥ 3.5 (Romano-Wolf m≈50 burnt holdout)
- **Required Sharpe: 2.47 annualized** — mathematically unreachable at IC=0.024.

Add the **continuous L/S turnover cost drag** (~85%/y at 60bps RT × 12 monthly rebalances): even gross Sharpe of 0.34 is fully consumed, leaving net Sharpe near zero.

**Verdict before run:** **REJECT — pre-doomed by IC × breadth math.**

This 5-minute back-of-envelope calculation closed all cache-enabled exploration on AlphaLens 10-feature alt_data stack. To break through the ceiling: must change one of (IC, breadth, holding-period vol) — typically requires a fresh feature class, not another selection-rule variant.

**Implementation as a pre-Phase-B sanity:**

```python
def ic_breadth_feasibility(
    bulk_ic: float,           # e.g., 0.024 from prior run
    n_eff_rebal: int,          # effective independent rebalances
    cost_drag_ann: float,      # annualized friction
    pass_threshold: float,     # locked pre-reg |t| threshold
) -> tuple[float, bool]:
    """Return (theoretical_max_t, feasible_bool). Use as Phase A gate."""
    t_max_gross = bulk_ic * (n_eff_rebal ** 0.5)
    # crude conversion to net t — assume cost drag ~ proportional to gross IR
    t_max_net = t_max_gross * (1 - cost_drag_ann / max(t_max_gross * 0.1, 0.01))
    return t_max_net, t_max_net >= pass_threshold

# Lock as pre-Phase-B abort condition:
t_max, feasible = ic_breadth_feasibility(bulk_ic=0.024, n_eff_rebal=35,
                                          cost_drag_ann=0.85, pass_threshold=3.5)
if not feasible:
    raise PreRunCeilingError(f"IC×breadth ceiling t_max={t_max:.2f} < threshold 3.5; ABORT")
```

**Why this matters as part of the methodology bundle:** without this template, "let me try one more selection rule" iterations on a saturated feature stack burn compute. With it, you can turn down infeasible designs in the design-memo phase, before any expensive backtest. Pairs naturally with the adversarial review pipeline (#1) — both reviewers can compute the ceiling independently and cross-check.

---

## When to use which template

| Scenario | Template |
|---|---|
| Drafting a new pre-reg, post-hoc to a FAIL | #1 adversarial review |
| Adopting a new commercial data subscription | #2 survivorship probe |
| Pre-Phase-A gate that might fail | #3 auto-pivot trigger |
| Same features, multiple variants | #4 feature parquet cache |
| Quick "is this even possible at threshold X?" | #5 IC×breadth ceiling |

---

## References

- AlphaLens session-close memo (2026-05-01 PM): [`memory/project_v5_v10_session_close_2026_05_01.md`](https://github.com/kamilpajak/AlphaLens) (private)
- v10 design + survivorship probe: [`docs/research/v10_analyst_features_design_2026_05_01.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/v10_analyst_features_design_2026_05_01.md)
- v6a-revised design (full adversarial review writeup): [`docs/research/v6a_mega_cap_exclusion_design_2026_05_01.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/v6a_mega_cap_exclusion_design_2026_05_01.md)
- v6c REJECTED-PRE-RUN (IC×breadth ceiling): [`docs/research/v6c_continuous_score_weighted_design_2026_05_01.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/v6c_continuous_score_weighted_design_2026_05_01.md)
- Survivorship probe driver: [`scripts/probe_yfinance_analyst_survivorship.py`](https://github.com/kamilpajak/AlphaLens/blob/main/scripts/probe_yfinance_analyst_survivorship.py)
- Grinold, R. C. (1989). *The Fundamental Law of Active Management*. JPM 15(3).
- Kerr, N. L. (1998). *HARKing: Hypothesizing After the Results are Known*. PSPR 2(3).
- Simmons et al. (2011). *False-Positive Psychology*. Psych Sci 22(11).
- Romano-Wolf (2005). *Stepwise multiple testing as formalized data snooping*. Econometrica 73(4).
