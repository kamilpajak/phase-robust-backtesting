# phase-robust-backtesting

Pre-registration ledger + multi-phase audit + Bonferroni thresholds for retail-quant strategy validation.

A small Python toolkit that addresses the two errors that retire most retail-quant strategies before they ever face capital:

1. **Phase-aliasing**: when your backtest rebalances every N days, the choice of which day-in-the-cycle you start on can swing reported Sharpe by 30–77 percentage points per year on otherwise-identical strategies. A single point estimate is unreliable.
2. **Multiple-testing inflation**: testing 25 variants and reporting the best inflates expected t-stat unless explicitly corrected. Without pre-registration discipline, every backtest a researcher has run silently lowers the bar future ones need to clear.

The toolkit is intentionally small: ~400 LOC of validation infrastructure, no DataFrame scaffolding, no scorer registry — just the discipline. You bring your own backtest engine; this library tracks frozen hypotheses and audits them across all rebalance phases.

## Origin

Crystallized after **5/5 paradigm failures** in the [AlphaLens project](https://github.com/kamilpajak/AlphaLens) (Layer 2b/2c/2d/2e/2f/2g — momentum, low-vol-value, insider activity, sector rotation, 8-K events, LLM-researcher) all failed multi-phase validation despite passing single-phase point estimates. Extended after a further **12 cumulative cross-class FAILs** on a 2024-2026 burnt holdout (alt_data + multi_source + nonlinear feature spaces, all selection-rule and model-class variants exhausted) — adding four more anti-patterns and five operational templates. The infrastructure built to detect those failures became this library.

- [`docs/anti_patterns.md`](docs/anti_patterns.md) — **nine mechanisms** that retire backtested strategies in production, with concrete numbers from the source incidents.
- [`docs/method_templates.md`](docs/method_templates.md) — **five operational templates** (adversarial review pipeline, survivorship probe, pre-registered auto-pivot trigger, feature parquet cache with input-only key, IC×breadth ceiling feasibility test) — reference patterns to copy into your own backtest harness.

## Install

```bash
pip install git+https://github.com/kamilpajak/phase-robust-backtesting.git
```

Requires Python 3.13+. Dependencies: `scipy`, `statsmodels`.

## Quick start

### 1. Pre-register a hypothesis

```python
from datetime import date
from pathlib import Path
from phase_robust_backtesting.ledger import Ledger, Registration

ledger = Ledger(Path("./preregistration"))

ledger.add(Registration(
    id="my_strategy_2026_q2",
    signal_class="momentum_x_quality",
    hypothesis="12-1m momentum × ROE TTM beats SPY net of 5bp cost on R2000",
    scorer_path="experiments/run_my_strategy.py",
    params_frozen={"top_n": 15, "holding": 60, "rebalance_stride": 5},
    periods={
        "is_start": "2015-01-01", "is_end": "2022-12-31",
        "oos_start": "2023-01-01", "oos_end": "2026-04-22",
    },
    success_criteria={"mode": "multi_phase", "min_alpha_t_pass": 1.5},
    registered_at=date.today(),
))

# What threshold must this hypothesis clear given prior tests in the class?
print(ledger.bonferroni_threshold("momentum_x_quality"))
# → critical |t| at α=0.05/N where N = count of registrations in the class
```

### 2. Run multi-phase audit on your experiment script

Your script must accept `--phase-offset N` and emit at least one log line in the form:

```
... | Sh gross=0.83 net=0.65 | excess gross=42.1% net=39.6% | α 4F=63.1% t=2.24 ...
```

Then:

```bash
phase-robust-audit \
    --script experiments/run_my_strategy.py \
    --rebalance-stride 5 \
    --out audit_2026_q2.json \
    -- --is-start 2015-01-01 --is-end 2022-12-31 --top-n 15
```

The driver invokes your script once per `phase_offset = 0..stride-1` (each as a subprocess), parses the metric line out of stderr, aggregates mean ± std ± verdict across phases, and writes the JSON report.

### 3. Read the verdict

```python
import json
from phase_robust_backtesting.multi_phase import robust_verdict, summarise_phase_results

audit = json.loads(Path("audit_2026_q2.json").read_text())
for cfg in audit["configs"]:
    print(cfg["config"], "→", cfg["verdict"], cfg["summary"]["alpha_t"])
```

Verdict matrix (see `phase_robust_backtesting/multi_phase.py`):

| Verdict | Condition |
|---|---|
| **PASS** | every phase α t ≥ 1.5 AND every phase excess net ≥ 0 |
| **MID** | mean α t ≥ 1.0 AND mean excess net > 0 AND not majority of phases negative |
| **FAIL** | mean α t < 1.0 OR mean excess net ≤ 0 OR majority of phases negative |

### 4. Complete the registration

```python
ledger.complete(
    "my_strategy_2026_q2",
    verdict="FAIL",
    mean_alpha_t=0.49,
    mean_excess_net=-0.057,
    audit_path="audit_2026_q2.json",
    completed_at=date.today(),
)
```

Re-completion of the same id raises — pre-registration discipline guarantees a hypothesis is graded exactly once. Re-running with different params requires a new id (and bumps the Bonferroni denominator for the next test in the class).

## Why these defaults?

- **Bonferroni at α=0.05** with class-conditional denominator: matches Harvey-Liu-Zhu (2016).
- **PASS gate at every-phase α t ≥ 1.5**: empirically harder than mean-only thresholds; rules out single-phase outliers that mask catastrophic phases.
- **MID verdict separate from FAIL**: regime-conditional sizing is a real intervention, not a euphemism for "kept alive on hope".
- **JSON ledger, ensure_ascii=False**: math symbols (α, ≥, −) stay readable in `git diff`.

## Documentation

- [`docs/anti_patterns.md`](docs/anti_patterns.md) — five mechanisms that killed backtested strategies in retail quant; concrete numbers from the AlphaLens postmortem.

## License

MIT.
