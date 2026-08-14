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

    # —— 方案A：止损触发 + 冷却禁买（5 个新闻日）——
    hist5 = {
        "2026-08-13": {"open": 100.0, "close": 100.0, "pct": 0.0},    # 首日pct=0 → hold
        "2026-08-14": {"open": 100.0, "close": 101.0, "pct": 1.0},    # buy → 15日开盘买(100)
        "2026-08-15": {"open": 100.0, "close": 95.0, "pct": -5.9},    # hold（持仓中）
        "2026-08-16": {"open": 88.0, "close": 96.0, "pct": 1.05},     # 开盘88→回撤12%止损卖; 决策buy(持仓跳过)
        "2026-08-17": {"open": 90.0, "close": 95.0, "pct": -1.0},     # 16日buy信号→冷却禁买
    }
    for d in ("2026-08-13", "2026-08-14", "2026-08-15",
              "2026-08-16", "2026-08-17"):
        (tmp / f"news_{d}.csv").write_text("title,content\n利好,业绩大增\n",
                                           encoding="utf-8-sig")
        (tmp / f"select_{d}.csv").write_text(
            "code,symbol,name,lbc,seal_amount,strategies,score\n"
            "600519,600519,贵州茅台,1,100000000,放量上涨,0.8\n",
            encoding="utf-8-sig")
    with mock.patch("backtest.load_hist_quotes", return_value=hist5), \
         mock.patch("backtest.cb.in_cooldown", return_value=False), \
         mock.patch("backtest.cb.record_sentiment"):
        r = bt.run_backtest("2026-08-13", "2026-08-17", sl_ratio=0.08,
                            sl_cool=2, grid=True)
        check("止损-16日开盘回撤12%触发止损卖", r["sl_sells"] == 1,
              f"sl_sells={r.get('sl_sells')}")
        check("止损-15日买入1笔", r["buys"] == 1, f"buys={r.get('buys')}")
        check("止损冷却-17日冷却期内禁买", r["buys"] == 1,
              "17日buy信号被冷却拦截，总买入仍1笔")

    # —— 方案B：个股情绪覆盖市场分（市场-0.5 → 个股+0.5 count≥3 → buy）——
    # 14日决策 buy → 15日开盘成交，故 end=08-15（15日select文件已有）
    for d in ("2026-08-13", "2026-08-14"):
        (tmp / f"news_{d}.csv").write_text("title,content\n利空,行业利空\n",
                                           encoding="utf-8-sig")
    with mock.patch("backtest.load_hist_quotes", return_value=hist5), \
         mock.patch("backtest.cb.in_cooldown", return_value=False), \
         mock.patch("backtest.cb.record_sentiment"), \
         mock.patch("backtest.filter_news.summarize",
                    return_value={"senti_score": -0.5}), \
         mock.patch("backtest.decision.stock_senti_map",
                    return_value={"600519": {"score": 0.5, "count": 6,
                                             "pos": 4, "neg": 0}}):
        r = bt.run_backtest("2026-08-13", "2026-08-15", senti_min=3, grid=True)
        check("个股情绪覆盖-市场负分仍按个股分买入", r["buys"] == 1,
              f"buys={r.get('buys')}")

    # —— 网格扫描模式（3×3×3=27 组，不崩溃且返回统计）——
    with mock.patch("backtest.load_hist_quotes", return_value=hist5), \
         mock.patch("backtest.cb.in_cooldown", return_value=False), \
         mock.patch("backtest.cb.record_sentiment"):
        bt.run_grid("2026-08-13", "2026-08-17")
    check("网格扫描 27 组执行无异常", True, "")

    bt.DATA_DIR = old_data
    bt.STOCKS = old_stocks
    print(f"backtest: {11 - fails}/11 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())