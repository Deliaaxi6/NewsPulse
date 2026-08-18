"""缁熶竴娴嬭瘯鍏ュ彛锛歱ython tests/run_tests.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_sentiment
import test_trading
import test_circuit
import test_indicators
import test_report_email
import test_fund_flow
import test_cyq
import test_net_guard
import test_daily_report
import test_strategies
import test_market_env
import test_select_stock
import test_telegram
import test_telegram_control
import test_llm_sentiment
import test_ml_advisor
import test_backtest
import test_stock_sentiment
import test_weekly_review
import test_alert
import test_run_all
import test_corporate


def main() -> int:
    suites = [
        ("sentiment", test_sentiment.main),
        ("trading", test_trading.main),
        ("circuit", test_circuit.main),
        ("indicators", test_indicators.main),
        ("email", test_report_email.main),
        ("fund_flow", test_fund_flow.main),
        ("cyq", test_cyq.main),
        ("net_guard", test_net_guard.main),
        ("daily_report", test_daily_report.main),
        ("strategies", test_strategies.main),
        ("market_env", test_market_env.main),
        ("select_stock", test_select_stock.main),
        ("telegram", test_telegram.main),
("telegram_control", test_telegram_control.main),
        ("llm_sentiment", test_llm_sentiment.main),
        ("ml_advisor", test_ml_advisor.main),
        ("backtest", test_backtest.main),
        ("stock_sentiment", test_stock_sentiment.main),
        ("weekly_review", test_weekly_review.main),
("alert", test_alert.main),
        ("run_all", test_run_all.main),
        ("corporate", test_corporate.main),
    ]
    total_fail = 0
    for name, fn in suites:
        print(f"=== {name} ===")
        try:
            rc = fn()
        except Exception as e:
            rc = 1
            print(f"[ERROR] {name} 寮傚父: {e}")
        total_fail += rc
        print()
    if total_fail:
        print(f"RESULT: FAILED ({total_fail} suite(s) with errors)")
        return 1
    print("RESULT: ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())