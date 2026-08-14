"""回测选股池回归测试（6 用例）：select 池优先 / 缺失回退 / 空文件回退 / 读取失败回退 / 池外股票交易。"""
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import backtest as bt
import pandas as pd


def main() -> int:
    fails = 0
    old_data = bt.DATA_DIR
    old_stocks = bt.STOCKS
    tmp = Path(tempfile.mkdtemp())
    bt.DATA_DIR = tmp

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    (tmp / "select_2026-08-13.csv").write_text(
        "code,symbol,name,lbc,seal_amount,strategies,score\n"
        "600519,600519,贵州茅台,2,100000000,平台突破,0.8\n"
        "000001,000001,平安银行,1,50000000,放量上涨,0.6\n",
        encoding="utf-8-sig")

    pool = bt._load_backtest_pool("2026-08-13")
    check("select 池优先", len(pool) == 2 and pool[0]["symbol"] == "600519", str(pool))

    pool = bt._load_backtest_pool("2026-08-01")
    check("select 缺失回退 STOCKS", pool == bt.STOCKS, f"len={len(pool)}")

    (tmp / "select_2026-08-02.csv").write_text("code,symbol,name,lbc,seal_amount,strategies,score\n",
                                               encoding="utf-8-sig")
    pool = bt._load_backtest_pool("2026-08-02")
    check("select 空文件回退 STOCKS", pool == bt.STOCKS)

    (tmp / "select_2026-08-03.csv").write_text("broken,not,csv,content", encoding="utf-8-sig")
    pool = bt._load_backtest_pool("2026-08-03")
    check("select 读取失败回退 STOCKS", pool == bt.STOCKS)

    hist = {}
    with mock.patch("backtest.load_hist_quotes", return_value={"2026-08-13": {"open": 1.0}}):
        bt._ensure_hist("999999", hist, "2026-08-01", "2026-08-14")
    check("按需加载池外股票行情", "999999" in hist)

    (tmp / "news_2026-08-13.csv").write_text("title,content\n利好新闻,公司业绩大增\n",
                                             encoding="utf-8-sig")
    (tmp / "news_2026-08-14.csv").write_text("title,content\n利空新闻,高管减持\n",
                                             encoding="utf-8-sig")
    (tmp / "select_2026-08-13.csv").write_text(
        "code,symbol,name,lbc,seal_amount,strategies,score\n"
        "600519,600519,贵州茅台,2,100000000,平台突破,0.8\n", encoding="utf-8-sig")
    (tmp / "select_2026-08-14.csv").write_text(
        "code,symbol,name,lbc,seal_amount,strategies,score\n"
        "600519,600519,贵州茅台,2,100000000,平台突破,0.8\n", encoding="utf-8-sig")
    with mock.patch("backtest.load_hist_quotes", return_value={
        "2026-08-13": {"open": 100.0, "close": 101.0, "pct": 1.0},
        "2026-08-14": {"open": 102.0, "close": 103.0, "pct": 1.0}}), \
         mock.patch("backtest.cb.in_cooldown", return_value=False), \
         mock.patch("backtest.cb.record_sentiment"):
        bt.run_backtest("2026-08-13", "2026-08-14")
        out = tmp / "backtest_2026-08-13_2026-08-14.csv"
        check("回测流程走 select 池并产出明细", out.exists(), str(out))

    bt.DATA_DIR = old_data
    bt.STOCKS = old_stocks
    print(f"backtest: {6 - fails}/6 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())