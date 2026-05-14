"""Multi-phase audit runner — eliminate phase-aliasing in stability checks.

Wraps any backtest experiment script that accepts a ``--phase-offset N``
flag and emits one or more headline log lines matching ``_RESULT_LINE``
below. Loops over ``phase_offset = 0..stride-1``, parses per-phase
metrics out of the child stderr, and writes an aggregated mean ± std ±
robust verdict report (JSON).

Usage::

  python -m phase_robust_backtesting.audit_multi_phase \\
      --script path/to/experiment.py \\
      --rebalance-stride 5 \\
      [extra args forwarded to the experiment script]

The experiment script is invoked once per phase as a subprocess. Any
arguments not recognised by this driver pass through to the script —
including ``--is-start``, ``--cost-half-spreads``, etc.

Result-line contract: the script must print at least one line containing
``Sh gross=<float> net=<float> | excess gross=<pct>% net=<pct>% |
α 4F=<pct>% t=<float>`` (compatible with AlphaLens' ``assess()`` output).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from phase_robust_backtesting.multi_phase import robust_verdict, summarise_phase_results

# Parses lines like:
#   "IS 2019-2022 | rw=1.0 vw=1.0 ADV≥$5M cost=5bps | n=201 ... Sh gross=0.83 net=0.65 |
#    excess gross=42.1% net=39.6% | α 4F=63.1% t=2.24 R²=0.049"
# and:
#   "IS 2015-2022 | vw=1.0 ADV≥$5M cost=5bps | ... Sh gross=0.42 net=0.21 |
#    excess gross=18.7% net=16.1% | α 4F=27.8% t=1.37"
#
# Optional `α-net 4F=...% t-net=...` trailing block captures the net-of-cost
# regression coefficients (paradigm-13 ev_fcff_yield material finding 2026-05-13:
# without these tokens, G4 cost-stress gates computed downstream are a structural
# no-op duplicate of G1 because the pre-existing `t` group is the gross/pre-cost
# regression t-stat — cost-invariant by construction). Experiment scripts that
# want a meaningful cost-stress gate MUST emit the trailing `α-net 4F=...% t-net=...`
# tokens; legacy scripts without those tokens degrade gracefully (alpha_t_net
# falls back to alpha_t and downstream consumers can detect via the
# `has_net_regression` flag in `_parse_results`).
#
# `nan|inf` literals are accepted on both `t` and `t-net` groups so degenerate
# Carhart regressions (zero residual variance, singular design) survive the
# regex without silently dropping the line from aggregation.
_RESULT_LINE = re.compile(
    r"Sh gross=(?P<sg>[-\d.]+) net=(?P<sn>[-\d.]+) \| "
    r"excess gross=(?P<eg>[-\d.]+)% net=(?P<en>[-\d.]+)% \| "
    r"α 4F=(?P<a>[-\d.]+)% t=(?P<t>[-\d.]+|nan|inf)"
    r"(?: \| α-net 4F=(?P<an>[-\d.]+)% t-net=(?P<tn>[-\d.]+|nan|inf))?"
)

# Log lines come prefixed with `<timestamp> INFO <name>: <content>`. Strip the
# prefix when grouping per-phase results — otherwise every subprocess
# invocation produces a unique config key and the aggregator never aggregates.
_LOG_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \w+ [\w._]+: ")


def _parse_results(stderr_text: str, phase_offset: int) -> list[dict[str, float]]:
    """Run `_RESULT_LINE` over each stderr line and emit one row per match.

    Pure function — split out from `_run_one_phase` for unit testing.
    """
    rows: list[dict[str, float]] = []
    for line in stderr_text.splitlines():
        m = _RESULT_LINE.search(line)
        if not m:
            continue
        # `alpha_t_net` is captured from the optional `α-net 4F=...% t-net=...`
        # trailing block. Falls back to `alpha_t` (gross) when the block is
        # absent so legacy logs from pre-2026-05-13 experiment scripts still
        # aggregate cleanly — downstream G4 cost-stress gates degrade to the
        # pre-fix no-op behaviour for those legacy rows, but at least the
        # phase doesn't silently drop from the aggregate.
        tn_raw = m.group("tn")
        an_raw = m.group("an")
        rows.append(
            {
                "sharpe_gross": float(m.group("sg")),
                "sharpe_net": float(m.group("sn")),
                "excess_gross_ann": float(m.group("eg")) / 100.0,
                "excess_net_ann": float(m.group("en")) / 100.0,
                "alpha_t": float(m.group("t")),
                "alpha_ann": float(m.group("a")) / 100.0,
                "alpha_t_net": float(tn_raw) if tn_raw is not None else float(m.group("t")),
                "alpha_net_ann": (
                    float(an_raw) / 100.0 if an_raw is not None else float(m.group("a")) / 100.0
                ),
                "has_net_regression": tn_raw is not None,
                "phase_offset": phase_offset,
                "raw_line": line.strip(),
            }
        )
    return rows


def _config_key_from_line(raw_line: str) -> str:
    """Strip the timestamp/log prefix and trailing per-phase stats; what's
    left is the parameter combo (period + ROE/vol weight + ADV + cost) that
    is shared across all phases of the same config — the right grouping key.
    """
    stripped = _LOG_PREFIX.sub("", raw_line)
    return stripped.split(" | n=")[0]


def _group_by_config(rows_per_phase: list[list[dict]]) -> dict[str, list[dict]]:
    """Flatten per-phase row batches and bucket by config key."""
    by_config: dict[str, list[dict]] = {}
    for phase_rows in rows_per_phase:
        for r in phase_rows:
            by_config.setdefault(_config_key_from_line(r["raw_line"]), []).append(r)
    return by_config


def _run_one_phase(
    script: Path,
    forwarded_args: list[str],
    phase_offset: int,
    stride: int,
) -> list[dict[str, float]]:
    """Invoke the experiment script with --phase-offset and parse result rows.

    Passes a per-phase --out under /tmp so subprocess invocations cannot
    clobber the canonical research docs (the experiment scripts' default
    --out paths point to docs/research/, which would overwrite historical
    sweeps with single-phase audit data). The /tmp file is unlinked
    after parsing — only the parsed rows from stderr are needed; the
    Markdown report is a transient artifact of the subprocess invocation.
    """
    out_path = Path(f"/tmp/audit_multi_phase_{script.stem}_p{phase_offset}.md")
    cmd = [
        sys.executable,
        str(script),
        "--rebalance-stride",
        str(stride),
        "--phase-offset",
        str(phase_offset),
        "--out",
        str(out_path),
        *forwarded_args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # Leave the /tmp report on disk for failure forensics; the
        # operator can grep it for diagnostic context.
        raise RuntimeError(
            f"phase {phase_offset} run failed (exit {proc.returncode}):\n"
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )
    rows = _parse_results(proc.stderr, phase_offset)
    # Successful phase: drop the transient Markdown report so multi-day
    # sweeps don't leave dozens of files in /tmp.
    out_path.unlink(missing_ok=True)
    return rows


def run_audit(
    script: Path,
    forwarded_args: list[str],
    *,
    rebalance_stride: int = 5,
    out: Path | None = None,
) -> int:
    """Run a multi-phase audit programmatically.

    Importable entry point — host applications can call this directly
    instead of spawning a subprocess to invoke the CLI. Avoids
    double-fork (e.g. an AlphaLens wrapper script that itself uses
    subprocess.run to run this module would swallow tracebacks and
    break Ctrl+C signal propagation).

    Parameters
    ----------
    script : Path
        Path to the experiment script that accepts ``--phase-offset N``.
    forwarded_args : list[str]
        Arguments to pass through to the experiment script verbatim
        (e.g. ``--is-start 2019-01-08 --cost-half-spreads 5``).
    rebalance_stride : int
        Number of phases to sweep (default 5 = weekly cadence with
        daily phase offset).
    out : Path | None
        Output path for the aggregated JSON report. Defaults to
        ``multi_phase_audit.json`` in the current working directory.

    Returns
    -------
    int
        Exit code: 0 on success. Raises :class:`RuntimeError` on
        per-phase failure (preserving the offending stderr tail).
    """
    if not script.exists():
        raise SystemExit(f"script path does not exist: {script}")
    script = script.resolve()
    if out is None:
        out = Path("multi_phase_audit.json")

    print(f"\n>>> Multi-phase audit: {script.name}", flush=True)
    print(f"    script: {script}", flush=True)
    print(f"    stride: {rebalance_stride}", flush=True)
    print(f"    phases: 0..{rebalance_stride - 1}", flush=True)

    all_rows: list[list[dict]] = []
    for phase in range(rebalance_stride):
        print(f"\n>>> phase {phase}/{rebalance_stride - 1}", flush=True)
        rows = _run_one_phase(script, forwarded_args, phase, rebalance_stride)
        if not rows:
            print(f"    WARNING: no result rows parsed for phase {phase}", flush=True)
        for r in rows:
            print(f"    {r['raw_line']}", flush=True)
        all_rows.append(rows)

    by_config = _group_by_config(all_rows)

    output: dict = {
        "script": str(script),
        "rebalance_stride": rebalance_stride,
        "configs": [],
    }
    for config_key, phase_rows in by_config.items():
        summary = summarise_phase_results(phase_rows)
        verdict = robust_verdict(phase_rows)
        output["configs"].append(
            {
                "config": config_key,
                "n_phases": len(phase_rows),
                "summary": summary,
                "verdict": verdict,
                "per_phase": [
                    {
                        "phase_offset": r["phase_offset"],
                        "sharpe_gross": r["sharpe_gross"],
                        "sharpe_net": r["sharpe_net"],
                        "excess_gross_ann": r["excess_gross_ann"],
                        "excess_net_ann": r["excess_net_ann"],
                        "alpha_t": r["alpha_t"],
                        # v0.2.3: net-of-cost regression fields. Always present
                        # in row dicts (with gross fallback for legacy logs);
                        # the `has_net_regression` flag tells downstream
                        # consumers whether the alpha_t_net is genuine or fallback.
                        "alpha_t_net": r.get("alpha_t_net", r["alpha_t"]),
                        "alpha_net_ann": r.get("alpha_net_ann"),
                        "has_net_regression": r.get("has_net_regression", False),
                    }
                    for r in phase_rows
                ],
            }
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2))
    print(f"\n>>> wrote {out}", flush=True)

    print("\n>>> Verdict summary")
    for entry in output["configs"]:
        cfg = entry["config"]
        v = entry["verdict"]
        s = entry["summary"]
        if "alpha_t" in s and "excess_net_ann" in s:
            print(
                f"  {cfg}\n"
                f"    verdict: {v} | "
                f"α t mean={s['alpha_t']['mean']:+.2f} (±{s['alpha_t']['std']:.2f}, "
                f"min={s['alpha_t']['min']:+.2f}, max={s['alpha_t']['max']:+.2f}) | "
                f"excess net mean={s['excess_net_ann']['mean'] * 100:+.1f}% "
                f"(±{s['excess_net_ann']['std'] * 100:.1f}pp)"
            )
        else:
            print(f"  {cfg}\n    verdict: {v} | (incomplete summary)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--script",
        type=Path,
        required=True,
        help="Path to the experiment script that accepts --phase-offset.",
    )
    ap.add_argument(
        "--rebalance-stride",
        type=int,
        default=5,
        help="Stride to sweep across (default 5 = weekly cadence).",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("multi_phase_audit.json"),
    )
    args, forwarded = ap.parse_known_args()
    return run_audit(
        args.script,
        forwarded,
        rebalance_stride=args.rebalance_stride,
        out=args.out,
    )


if __name__ == "__main__":
    sys.exit(main())
