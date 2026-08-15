"""一键入口回归测试（5 用例）：休市日早退 / 交易日全链路 / 日历不可用 fail-open / 步骤失败告警中止。"""
import sys
import contextlib
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import run_all


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    steps = ("select_stock", "fetch_news", "filter_news", "decision",
             "sim_account", "daily_report")

    def run(is_trading, expect_calls):
        calls = []
        stack = contextlib.ExitStack()
        for m in steps:
            stack.enter_context(mock.patch.object(
                getattr(run_all, m), "main",
                lambda *a, _m=m, **k: calls.append(_m)))
        stack.enter_context(mock.patch.object(
            run_all.fund_flow, "is_trading_day", return_value=is_trading))
        stack.enter_context(mock.patch.object(run_all.alert, "notify",
                                              return_value=False))
        with stack:
            run_all.main()
        return calls

    calls = run(False, [])
    check("休市日早退 不执行任何步骤", calls == [], str(calls))

    calls = run(True, steps)
    check("交易日全链路执行", calls == list(steps), str(calls))

    calls = run(None, steps)
    check("日历不可用 fail-open 照常执行", calls == list(steps), str(calls))

    calls = []
    alerts = []
    after = []
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(run_all.select_stock, "main",
                                          side_effect=RuntimeError("boom")))
    stack.enter_context(mock.patch.object(run_all.fetch_news, "main",
                                          side_effect=lambda *a, **k: after.append("fetch")))
    stack.enter_context(mock.patch.object(run_all.fund_flow, "is_trading_day",
                                          return_value=True))
    stack.enter_context(mock.patch.object(run_all.alert, "notify",
                                          side_effect=lambda *a, **k: alerts.append(a)))
    with stack:
        try:
            run_all.main()
        except RuntimeError:
            pass
    check("步骤失败告警", len(alerts) == 1 and "失败" in alerts[0][0]
          and "选股" in alerts[0][0] and "boom" in alerts[0][1], str(alerts))
    check("步骤失败中止 后续不执行", after == [], str(after))

    print(f"run_all: {5 - fails}/5 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
