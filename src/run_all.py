"""NewsPulse 一键入口（demo 版）：新闻→情绪→决策→撮合→报告。
任一步骤崩溃 → 告警（Telegram 双通道）并中止后续步骤（fail-stop，避免基于
残缺数据的误导日报）。"""
import sys
import datetime as dt

import fetch_news
import filter_news
import decision
import sim_account
import daily_report
import select_stock
import fund_flow
import alert
import pnl_report

_STEPS = (
    ("选股", select_stock),
    ("新闻", fetch_news),
    ("情绪", filter_news),
    ("决策", decision),
    ("撮合", sim_account),
    ("报告", daily_report),
    ("盈亏", pnl_report),
)


def _step(name, mod, date_str):
    print(f"[run] 步骤 {name}")
    try:
        mod.main(date_str)
    except Exception as e:
        print(f"[error] 步骤 {name} 失败: {e}")
        alert.notify(f"全链路步骤失败: {name}",
                     f"{date_str} 步骤「{name}」异常: {type(e).__name__}: {e}")
        raise


def main():
    date_str = dt.date.today().isoformat()
    print(f"=== NewsPulse demo {date_str} ===")
    if fund_flow.is_trading_day(date_str) is False:
        print(f"[info] {date_str} 休市日，跳过今日全链路（避免空新闻/旧数据日报）")
        return
    for name, mod in _STEPS:
        _step(name, mod, date_str)
    print("=== done ===")


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    main()