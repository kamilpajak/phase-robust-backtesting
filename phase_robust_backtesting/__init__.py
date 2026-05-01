"""Phase-robust strategy validation toolkit.

Three small libraries, one shared discipline: every strategy hypothesis is
pre-registered before testing, audited across all rebalance phases, and
graded against a class-conditional Bonferroni threshold.

Modules:
- ``ledger``: file-backed registry of frozen hypotheses (one-shot completion,
  per-signal-class Bonferroni denominator).
- ``multi_phase``: aggregator over ``phase_offset = 0..stride-1`` runs.
  ``robust_verdict`` returns PASS/MID/FAIL using the full phase distribution
  rather than a single point estimate.
- ``multiple_testing``: Bonferroni critical |t|, BH-FDR adjusted p-values.
- ``audit_multi_phase``: subprocess driver that loops a backtest experiment
  script over every phase and writes the aggregated verdict JSON.

Solves the two errors that retire most retail-quant strategies:
  - **Phase-aliasing**: a single rebalance-day offset can swing reported
    Sharpe by 30-77pp/y on otherwise-identical strategies.
  - **Multiple-testing inflation**: testing 25 variants and reporting the
    best inflates expected t-stat unless explicitly corrected.

References: Harvey-Liu-Zhu (2016) ".. and the Cross-Section of Expected
Returns"; Bailey-López de Prado (2014) "The Sharpe Ratio Efficient Frontier".
"""

__version__ = "0.1.0"
