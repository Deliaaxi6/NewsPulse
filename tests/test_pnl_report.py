"""盈亏日报测试：pnl_summary 口径（现金+持仓市值）/累计/今日/回落/空仓/无数据 fail-open。
全部用临时目录写真实 portfolio.csv，避免 mock 分叉。"""
import sys
import tempfile
from pathlib import Path
import unittest.mock as mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pnl_report

DF_TYPE = {"stock": str}


def _write(td, df):
    (td / "portfolio.csv").write_text(
        df.to_csv(index=False), encoding="utf-8-sig")


def _rows(days, cash: float, hold_sets: dict) -> pd.DataFrame:
    n = len(days)
    rows = []
    for i, d in enumerate(days):
        holds = hold_sets.get(d, {})
        c = cash
        for stock, (shares, cost, price) in holds.items():
            rows.append({"date": d, "stock": stock, "shares": shares, "cost": cost,
                         "market_value": shares * price, "cash": c,
                         "leverage": 1.0, "total_value": c + shares * price})
        if not holds:
            rows.append({"date": d, "stock": "000000", "shares": 0.0, "cost": 0.0,
                         "market_value": 0.0, "cash": c, "leverage": 1.0, "total_value": c})
    return pd.DataFrame(rows)


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        with mock.patch.object(pnl_report, "DATA_DIR", td):
            # 1 无文件 fail-open
            check("无 portfolio 文件返回空", pnl_report.pnl_summary("2026-09-02") == {})

            # 2 空仓
            _write(td, _rows(["2026-09-01", "2026-09-02"], 50000.0, {"2026-09-02": {}}))
            s2 = pnl_report.pnl_summary("2026-09-02")
            check("空仓：总资产=现金", s2 and s2["assets"] == 50000.0 and s2["position_count"] == 0)

            # 3 持仓运算
            mv = 2600 * 12.17 + 100 * 181.48
            _write(td, _rows(["2026-08-31", "2026-09-02"], 30000.0, {
                "2026-09-02": {"600508": [2600, 10.87, 12.17], "603186": [100, 167.55, 181.48]}}))
            s3 = pnl_report.pnl_summary("2026-09-02")
            check("总资产=现金+市值", s3["assets"] == round(30000.0 + mv, 2), s3["assets"])
            check("累计盈亏额", s3["total_pnl"] == round(30000.0 + mv - 100000, 2))
            check("累计盈亏率", abs(s3["pnl_pct"] - (30000.0 + mv - 100000) / 100000 * 100) < 1e-9)
            fl = (2600 * 12.17 - 2600 * 10.87) + (100 * 181.48 - 100 * 167.55)
            check("浮动盈亏=持仓浮盈和", abs(sum(p["pnl"] for p in s3["positions"]) - round(fl, 2)) < 1e-6)

            # 4 今日盈亏 vs 上一交易日
            _write(td, pd.concat([
                _rows(["2026-09-01"], 40000.0, {"2026-09-01": {"600508": [2600, 10.87, 11.17]}}),
                _rows(["2026-09-02"], 30000.0, {"2026-09-02": {"600508": [2600, 10.87, 12.17]}}),
            ]))
            s4 = pnl_report.pnl_summary("2026-09-02")
            prev = 40000.0 + 2600 * 11.17
            cur = 30000.0 + 2600 * 12.17
            check("今日盈亏=当日-上个交易日", s4["day_pnl"] == round(cur - prev, 2), s4["day_pnl"])
            check("环比日期取上交易日", s4["prev_date"] == "2026-09-01")

            # 5 截止日晚于最后数据 → 回落最后可用日
            _write(td, _rows(["2026-09-01", "2026-09-02"], 30000.0,
                             {"2026-09-01": {"000070": [1400, 16.07, 15.66]},
                              "2026-09-02": {"000070": [1400, 16.07, 15.66]}}))
            s5 = pnl_report.pnl_summary("2026-09-03")
            check("截止日回落", s5["date"] == "2026-09-02" and s5["assets"] == round(30000.0 + 1400 * 15.66, 2), s5["date"])

            # 6 _fmt 文本
            t = pnl_report._fmt({"date": "2026-09-02", "assets": 100000.0, "cash": 200.0,
                                 "total_pnl": -2818.0, "pnl_pct": -2.818,
                                 "day_pnl": 300.0, "day_pct": 0.3,
                                 "prev_date": "2026-09-01", "position_count": 1,
                                 "positions": [{"stock": "600508", "shares": 2600.0,
                                                "price": 12.17, "pnl": 1200.0}]})
            check("文本含累计盈亏", "-2,818" in t and "-2.82%" in t)
            check("文本含持仓明细", "600508" in t and "+1200" in t)

            # 7 空 summary → 空文本
            check("空 summary 文本为空", pnl_report._fmt({}) == "")

    print(f"pnl_report: {7 - fails}/7 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())