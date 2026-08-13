"""统一测试入口：python tests/run_tests.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_sentiment
import test_trading
import test_circuit
import test_indicators
import test_report_email


def main() -> int:
    suites = [
        ("sentiment", test_sentiment.main),
        ("trading", test_trading.main),
        ("circuit", test_circuit.main),
        ("indicators", test_indicators.main),
        ("email", test_report_email.main),
    ]
    total_fail = 0
    for name, fn in suites:
        print(f"=== {name} ===")
        try:
            rc = fn()
        except Exception as e:
            rc = 1
            print(f"[ERROR] {name} 异常: {e}")
        total_fail += rc
        print()
    if total_fail:
        print(f"RESULT: FAILED ({total_fail} suite(s) with errors)")
        return 1
    print("RESULT: ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())