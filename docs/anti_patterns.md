# Anti-pattern catalog

**Nine mechanisms** that retire backtested strategies in production. Each entry pairs a representative example (numbers from the [AlphaLens postmortem](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/paradigm_failures_postmortem.md)) with a concrete remediation.

Mechanisms 1-5 (phase-aliasing, single-phase verdict, multiplicity, regime overfit, liquidity illusion) are the original AlphaLens 5/5 paradigm-failure crystallization. Mechanisms 6-9 were added after the 2024-04-30 → 2026-04-30 burnt-holdout exhaustion (12 cumulative cross-class FAILs across alt_data + multi_source + nonlinear feature spaces).

If your validation pipeline doesn't already cover all nine, the toolkit in this repo (`ledger`, `multi_phase`, `multiple_testing`, `audit_multi_phase`) plus the templates in [`docs/method_templates.md`](method_templates.md) is the minimum viable backstop.

---

## 1. Phase-aliasing in strided rebalance backtests

When `rebalance_stride > 1` and `top_n` is small, the choice of which day-in-the-cycle the simulation starts on samples a different rebalance calendar — and therefore a different portfolio every time. Reported Sharpe varies wildly by phase even though the strategy is the same.

**Example — mom+lowvol combo (2026-04-29):** OOS 2023–2026, `vol_w=1.0`, ADV ≥ \$5M, 5bp half-spread, `stride=5`, `top_n=15`. Single-phase OOS Sharpe 0.55, αt=1.45. Looked like a candidate.

Multi-phase audit:

| Phase | αt | excess net | Sharpe net |
|---:|---:|---:|---:|
| 0 | +1.55 | +21.8% | +0.61 |
| 1 | +1.66 | +44.0% | +0.69 |
| 2 | −0.39 | −33.9% | −0.46 |
| 3 | −0.53 | −67.0% | −0.45 |
| 4 | +0.17 | +6.5% | +0.03 |
| **mean** | **+0.49** | **−5.7%** | — |
| **dispersion** | — | **44.5pp** | — |

Mean αt fell from headline 1.45 to phase-distributed 0.49. Two of five phases produced excess net below −33%. The headline was a phase-0 sample, not a population estimate.

**Remediation.** Run the backtest at every `phase_offset = 0..stride-1` and verdict on the distribution, not the point estimate. `audit_multi_phase --script <your_script>` does the loop; `multi_phase.robust_verdict` returns PASS / MID / FAIL using every-phase + mean checks.

---

## 2. Single-phase point estimate as verdict

A close cousin of #1: even at `stride=1` (no phase choice), a single backtest's Sharpe / α / t-stat is a high-variance estimator. Treating it as the population truth invites IS→OOS catastrophe.

**Example — Layer 2d insider Form 4 cluster screen (2026-04-24):** Carhart-4F α t-stat in-sample 2015–2022 was **+2.14**. Looked like a clean factor. Out-of-sample 2023–2026: t-stat **+0.68**. Net excess flipped negative by ~30 percentage points.

**Example — tri-factor (2026-04-29):** OOS phase-0 αt = **+2.08** (first config in the entire AlphaLens project to clear nominal t > 2.0). Multi-phase mean αt across 5 phases: **+0.34**. Mean excess net: **−8.5%/y**.

**Remediation.** Pair every single-phase result with at least one of:
- multi-phase audit (Mechanism #1's solution),
- formal halves test on a held-out tail of the IS window (lock-universe required),
- a Bonferroni-adjusted threshold (Mechanism #3).

Treat any OOS αt ≥ 2 from a single sample with active suspicion until distributional evidence backs it.

---

## 3. Multiple-testing inflation (max-of-N selection bias)

If you tested 25 variants of a strategy and reported the best, the expected reported t-stat is inflated by the order statistic of the maximum, not the mean. Without pre-registration discipline, every backtest you've ever run silently lowers the bar new ones must clear.

**Example — AlphaLens 2026-04-29 strategy search:** ~30 variants tested in one day across pure momentum, pure contrarian, mom+lowvol combo, regime overlay, long-short, horizon variants, FF5+UMD, breadth gates, min-variance weighting. Best result reported: tri-factor OOS αt = +2.08. Bonferroni n=30 → required |t| ≈ **3.10**. The headline was nominal, not Bonferroni-passing.

The retrospective report noted this as a footnote ("multiple-testing not corrected"). Without enforcement, the discipline becomes optional and the next session repeats the trap.

**Remediation.** Pre-register the hypothesis BEFORE running the audit. The ledger counts every entry in the signal class; the corrected critical |t| at α = 0.05/N rises with each test:

```python
ledger.add(Registration(...))
print(ledger.bonferroni_threshold("momentum_x_quality"))  # uses current count
```

Re-running with different parameters requires a new id (and bumps the denominator). The ledger refuses to re-complete an existing id, so post-hoc parameter selection cannot rewrite history.

---

## 4. IS→OOS regime overfit

A strategy can be genuinely real in the in-sample period and genuinely broken out-of-sample because the regime changed — not because the model overfit. Halves stability + multi-period subsamples reveal regime fragility that pooled-IS αt hides.

**Example — Layer 2c lean (low-vol value, 2026-04-19):** 5-year IS Sharpe net **0.25**, FF3 α t-stat **0.14**. OOS 2023–2026 destroyed by mega-cap-momentum regime; the entire concentration premium that drove low-vol-value flipped sign.

**Example — mom+lowvol regime hole:**

| Subsample | Sharpe | excess | αt |
|---|---:|---:|---:|
| IS 2011–2016 | 0.77 | +28.0% | +1.82 |
| IS 2017–2022 | 0.16 | **−11.3%** | +0.63 |
| IS pooled 2011–2022 | 0.43 | +7.9% | +1.65 (masks failure) |
| OOS 2023–2026 | 0.75 | +21.5% | +1.45 |

Pooled IS αt was a respectable 1.65; the 2017–2022 subsample was already negative excess but the pooled average masked it. Four orthogonal experiments (long-short, regime overlay, SPY-hedge, horizon variants) failed to close the regime hole — it was structural, not filterable.

**Remediation.**
- Run halves stability with `--lock-universe` so per-period universes don't diverge.
- For multi-phase audits, lock-universe is also mandatory — narrower universes in halves create apples-to-oranges comparisons.
- If the strategy passes mean-phase but a single phase is materially negative, the verdict matrix returns MID, not PASS. MID demands regime-conditional sizing (halve position size, deploy only when a regime gate passes), not full deployment.
- If the strategy fails mean-phase, the verdict is FAIL. There is no save through ensemble or regime overlay — that's data-mining the failure.

---

## 5. Liquidity illusion (zero-cost assumption on unscalable alpha)

A backtest with zero transaction cost on a tradeable universe with no ADV floor will frequently report dramatic alpha generated entirely by names that cannot actually be traded at scale. Apply realistic costs and a per-rebalance ADV floor; the alpha vanishes — or worse, flips negative.

**Example — Layer 2b themed momentum (2026-04-22):** Zero-cost IS Sharpe ≈ 1.5. Apply 5–15bp half-spread and 10% participation cap on dollar-ADV: Sharpe drops below 0, and at retail-feasible ADV ≥ \$5M the alpha is fully consumed by cost. Headline became "momentum overfit + cost eats signal."

**Example — pure 60d-DD/5d-bounce contrarian (2026-04-29):**

| ADV floor | gross α | net α (5bp) |
|---|---:|---:|
| \$0M (no floor) | +150%/y | +145% |
| \$1M | +21.3% | +13.2% |
| **\$5M** | −48.8% | **−52%** |
| \$20M | −45.4% | −51% |
| \$100M | −34.4% | −42% |

The 150%/y headline at zero ADV was 100% tail-rebound artifact of un-tradeable names. Removing the bottom 1% of the universe by liquidity (ADV < \$1M) cut gross α from 150% to 21%. Removing names below \$5M ADV flipped α negative by 200pp.

**Remediation.** Build cost into the backtest at the model level, not as a post-hoc adjustment:
- Realistic cost model: half-spread + impact (impact ∝ √(participation × volatility) is a standard floor).
- Per-rebalance ADV floor as a hard universe filter, not a soft penalty. Names below the floor never enter the candidate set.
- Cost-stress sweep at minimum two configurations per audit (e.g., 5bp + 15bp half-spread × \$5M + \$20M ADV) — pre-registered into the params block, not added later when results disappoint.

If your strategy survives these and Mechanisms #1–#4, it has cleared the methodology bar for forward-walking. If it doesn't, no amount of further tuning will save it on real capital.

---

## 6. Rank-blindness in linear-Lasso ranking models with tail-aggressive selection

A linear-Lasso fit with `target_transform='rank'` minimizes MSE between predictions and per-asof rank percentiles. The objective rewards getting the **bulk** ranking right; it has no penalty for the model under-predicting the **magnitude** of tail-event returns. When a downstream selection rule (top-N, decile L/S, etc.) magnifies the tail to make the trade actionable, large positive returns in the bottom decile (e.g., short-squeeze winners) crush the spread that the bulk ranking would otherwise show as positive.

**Example — alt_data v3/v4 (2026-05-01):**

| Variant | αt | Holdout mean rank-IC | Selection-rule pool size |
|---|---:|---:|---:|
| v3 (top-30 long EW) | **−4.32** | +0.0260 | ~30 names (tail) |
| v4 (decile L/S, SI≤15%) | **−2.57** | +0.0260 | ~97/leg (decile) |

Both v3 and v4 had IDENTICAL bulk holdout rank-IC of +0.026 — the model genuinely sorted the cross-section in the right direction at population level. Both FAIL'd because the selection rule concentrated weight in tails where regime events (short squeeze in 2024-25) flipped sign on individual names the bulk-MSE-trained Lasso couldn't see.

**Remediation.**
- Pair rank-target Lasso with **continuous score-percentile-weighted portfolios** (`w_i ∝ rank_i − 0.5`) when the objective is bulk-IC harvest, not tail concentration.
- If tail selection is necessary (decile or narrower), add an **explicit magnitude-aware loss** (Huber, quantile with proper hessian, asymmetric pinball) to the model — not just rank target.
- Inspect the ratio of nonzero coefficient magnitude to per-asof score variance; if Lasso shrinks all features to ~0.01 magnitude on rank-target, the model is bulk-only.

---

## 7. Alpha illusion vs T-bill (long leg without cap-matched benchmark)

A long-only strategy can show "+20%/y" absolute return and look promising while the cap-matched benchmark in the same window did +60-70%/y. Carhart-4F sometimes absorbs this via SMB / Mkt-RF betas, sometimes it doesn't — especially under extreme regime concentration (e.g., 2024-25 mega-cap rally). Decomposing excess vs SPY into excess vs MDY (or RSP, or universe-EW) reveals what fraction of the gap was benchmark-concentration drift vs genuine factor underperformance.

**Example — alt_data v5 long-only (2026-05-01):** Long top-decile EW, same Lasso fit as v4. Long-leg returned +29.9 / +16.2 / +10.9 %/y across 2024 partial / 2025 full / 2026 partial sub-periods (mean ≈ +20.6%/y, matching v4's reported long-leg). αt vs SPY: **−3.20**, excess −37.3%/y net.

**v6a-revised follow-up:** same Lasso refit on non-mega-cap subset, MDY benchmark.

| Sub-period | Long ann | SPY ann | gap vs SPY | MDY ann | gap vs MDY |
|---|---:|---:|---:|---:|---:|
| 2024 partial | +34.1% | +75.8% | **−45.9pp** | +42.8% | **−8.7pp** |
| 2025 full | +12.4% | +67.6% | −51.4pp | +40.3% | −27.9pp |
| 2026 partial | +10.9% | −68.7% | +79.5pp | −4.6% | +15.5pp |

αt vs MDY = **−0.67** (vs −3.20 vs SPY). SPY mega-cap concentration explained ~58% of v5's catastrophic gap. **But mid-cap also rallied 40%/y** in 2025 — so even cap-matched benchmark crushed the long leg. The "+20.6%/y" was alpha illusion against ANY rally regime benchmark, not just mega-cap-driven SPY.

**Remediation.**
- Always pair long-only verdicts with **cap-matched benchmark Carhart regression** (MDY for mid-cap selections, IWM for small-cap, RSP for cap-weighted-S&P-EW comparisons).
- Decompose `αt vs SPY` into `αt vs cap-matched` to separate **concentration drift** from **factor failure**. If gap collapses 50%+ when benchmark switches, the strategy is benchmark-vulnerable, not necessarily alpha-bearing.
- Pre-register both benchmarks in the params block; report primary metric vs cap-matched, descriptive vs SPY.

---

## 8. Model-class swap doesn't rescue a feature bottleneck

When a linear model fails on a feature stack, switching to non-linear (tree boosting, neural, kernel) often appears as the next defensible move. But if the population-level rank-IC of the features is small (~0.02) and the failures span selection rules, the bottleneck is the **feature space**, not the functional form. Tree boosting on a saturated feature space will produce sign-flipped predictions, not rescue.

**Example — nonlinear_alt_data v9 LightGBM-MSE (2026-05-01):** Same 10-feature alt_data stack as v3/v4 (linear-Lasso, all FAIL'd). v9 swap to LightGBM regression with rank target. Adversarial-review-vetted hyperparameters (max_depth=5, min_child_samples=500, MSE objective, no quantile-loss tail-blindness).

| Metric | v4 (linear-Lasso) | v9 (LightGBM-MSE) | Δ |
|---|---:|---:|---:|
| Holdout mean rank-IC | +0.0260 | **−0.0123** | **sign-flip** |
| In-CV IR | 0.338 | **−0.22** (NEGATIVE) | catastrophic |
| αt | −2.57 | **−0.27** | nominally less bad, but rank-IC inverted |
| Decile turnover | ~12%/rebal | **3× higher** | cost drag 12.6%/y |

LightGBM produced an **anti-signal** vs linear's weak +signal. Tree boosting amplified noise across saturated features rather than extracting structure. Five experiments × 3 model classes (linear-Lasso, two-stage Lasso, LightGBM-MSE) all failed on the same feature stack — bottleneck SETTLED as features.

**Remediation.**
- Before pivoting to a fancier model, run a **bulk rank-IC sanity** on the existing features: if population-level Spearman correlation of predictions vs forward returns is < 0.03, no functional form will mechanically extract enough Sharpe (see Mechanism #9 IC×breadth ceiling).
- Demand a model swap **introduce new information**, not just re-fit existing features. New information = new feature class (analyst events, options-implied, news embeddings), longer / shorter horizon, or different universe.
- Track "model class iterations on identical features" as part of the program-level Bonferroni count — multiplicity inflation does not reset on model class change.

---

## 9. Data provider survivorship-broken delisted retention

Free / aggregator data sources frequently prune historical data for delisted tickers, creating a survivorship bias that systematically excludes the negative tail (companies whose declining fundamentals / negative analyst revisions / insider sales preceded delisting). This bias inflates apparent factor predictivity by removing the worst outcomes from the training set, then masquerades as legitimate alpha until you back-test on a complete-survivorship universe.

**Example — yfinance `upgrades_downgrades` analyst event probe (2026-05-01):** Pre-registered as gate 2 of v10 design (analyst revision feature class). Methodology: sample n=200 delisted tickers (2018-2024 delisting window) vs n=200 active tickers (PIT universe 2024-01), probe yfinance's analyst event endpoint for each, bootstrap z-test on event-rate ratio.

| Cohort | Mean event count | Non-empty rate |
|---|---:|---:|
| Delisted (n=200) | 0.16 | **2.5%** |
| Active (n=200) | 63.15 | **98.5%** |
| Ratio | 0.003 | — |
| z-stat under H₀=1.0 | **620** | — |
| p-value (H₁: ratio < 1) | **<0.0001** | — |

yfinance prunes delisted ticker analyst histories almost entirely. A v10 backtest using this data would have produced systematic look-ahead leak: Lasso would learn "missing analyst data = future delister = bad return" and apparent alpha would track survivorship, not signal. **v10 ABORTED-PRE-PHASE-B** before any compute on the model itself.

**Remediation.**
- Add **survivorship probe gate** to the pre-registration JSON — pre-commit to abort if the data provider can't demonstrate ≥50% delisted-ticker coverage relative to active.
- Run the probe on each new commercial subscription before committing to the data source. Templates in [`docs/method_templates.md`](method_templates.md) (#2).
- If the probe FAILs, pre-register an **objective auto-pivot trigger** that switches to a fall-back hypothesis without requiring post-hoc HARKing (Mechanism #3) decisions.

---

## References

- AlphaLens postmortem: [`docs/research/paradigm_failures_postmortem.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/paradigm_failures_postmortem.md)
- Methodology audit (phase-aliasing): [`docs/research/methodology_audit_2026_04_29.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/methodology_audit_2026_04_29.md)
- Mom+lowvol verdict: [`docs/research/mom_lowvol_combo_multi_phase_verdict.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/mom_lowvol_combo_multi_phase_verdict.md)
- Tri-factor verdict: [`docs/research/tri_factor_multi_phase_verdict.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/tri_factor_multi_phase_verdict.md)
- Strategy validation playbook: [`docs/research/strategy_validation_playbook.md`](https://github.com/kamilpajak/AlphaLens/blob/main/docs/research/strategy_validation_playbook.md)
- Harvey-Liu-Zhu (2016) "... and the Cross-Section of Expected Returns" — multiple-testing framework for factor zoo
- Bailey-López de Prado (2014) "The Sharpe Ratio Efficient Frontier" — single-Sharpe variance + selection bias
