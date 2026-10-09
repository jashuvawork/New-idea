"""CI: no new enable_live_trading forks outside audited modules."""

import subprocess
import sys
from pathlib import Path


def test_enable_live_trading_allowlist_script():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_enable_live_trading_rule_forks.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(script.parents[2]),
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
