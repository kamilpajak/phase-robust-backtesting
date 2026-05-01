"""CLI smoke test for the multi-phase audit driver entry point.

Catches import-time crashes and missing-flag regressions in
``phase_robust_backtesting.audit_multi_phase`` without invoking any
backtest subprocess. Cheap (≈100ms) and runs as part of the regular
``unittest discover`` sweep.
"""

from __future__ import annotations

import subprocess
import sys
import unittest


class CLISmokeTests(unittest.TestCase):
    def test_audit_help_exits_zero_with_expected_marker(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "phase_robust_backtesting.audit_multi_phase",
                "--help",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--script", result.stdout)
        self.assertIn("--rebalance-stride", result.stdout)


if __name__ == "__main__":
    unittest.main()
