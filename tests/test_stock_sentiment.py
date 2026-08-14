"""个股情绪测试（方案B）：分组聚合 + decision 覆盖/回退。"""
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import filter_news
import decision


def test_stock_sentiment_group() -> int:
    """stock_sentiment：按 related_stocks 分组；市场新闻（URL）不参与。"""
    fails = 0
    df = pd.DataFrame([
        {"time": "2026-08-14 09:00", "title": "A 利好", "content": "",
         "related_stocks": "600519", "senti": "bull"},
        {"time": "2026-08-14 09:00", "title": "A 利空", "content": "",
         "related_stocks": "600519", "senti": "bear"},
        {"time": "2026-08-14 09:00", "title": "B 中性", "content": "",
         "related_stocks": "000858", "senti": "neutral"},
        {"time": "2026-08-14 09:00", "title": "市场新闻", "content": "",
         "related_stocks": "https://finance.eastmoney.com/x.html", "senti": "bull"},
        {"time": "2026-08-14 09:00", "title": "池外股票", "content": "",
         "related_stocks": "999999", "senti": "bull"},
        {"time": "2026-08-14 09:00", "title": "多代码脏数据", "content": "",
         "related_stocks": "600519,000858", "senti": "bull"},
    ])
    res = filter_news.stock_sentiment(df, {"600519", "000858"})
    cases = [
        (res.get("600519", {}).get("score"), 0.0, "600519 (1bull-1bear)/2"),
        (res.get("600519", {}).get("count"), 2, "600519 条数=2"),
        (res.get("000858", {}).get("score"), 0.0, "000858 中性 0.0"),
        (res.get("000858", {}).get("count"), 1, "000858 条数=1"),
        ("999999" in res, False, "池外代码不参与"),
        (len(res), 2, "仅池内 2 只"),
    ]
    for got, expect, note in cases:
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 个股情绪分组 {note:24s} -> {got} (expect {expect})")
    res_empty = filter_news.stock_sentiment(pd.DataFrame(), {"600519"})
    ok = res_empty == {}
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 空 df -> {{}}")
    return fails


def test_stock_senti_map(tmp: Path) -> int:
    """stock_senti_map：文件缺失/损坏 → {}；正常读取返回 dict。"""
    fails = 0
    old = decision.DATA_DIR
    decision.DATA_DIR = tmp
    try:
        got = decision.stock_senti_map("2026-08-14")
        ok = got == {}
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 文件缺失 -> {{}}")
        pd.DataFrame([{"date": "2026-08-14", "stock": "600519", "score": 0.12,
                       "count": 5, "pos": 3, "neg": 1}]).to_csv(
            tmp / "stock_sentiment_2026-08-14.csv", index=False, encoding="utf-8-sig")
        got = decision.stock_senti_map("2026-08-14")
        ok = got.get("600519", {}).get("count") == 5 and got.get("600519", {}).get("score") == 0.12
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 正常读取 -> {got}")
    finally:
        decision.DATA_DIR = old
    return fails


def test_callback_overbought() -> int:
    """方案C辅助：回调策略判定 + 超买降权判定（纯函数）。"""
    fails = 0
    cases = [
        (["回踩年线"], True, "回踩年线→回调"),
        (["低波动启动"], True, "低波动启动→回调"),
        (["无大跌回踩"], True, "无大跌回踩→回调"),
        (["海龟突破"], False, "海龟突破→动量"),
        ([], False, "无策略→动量"),
        (["回踩年线", "海龟突破"], True, "含回调即回调"),
    ]
    for strats, expect, note in cases:
        got = decision._is_callback(strats)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 回调策略 {note:18s} -> {got} (expect {expect})")
    ob_cases = [
        ({"rsi": {"rsi": 85}}, {"lbc": 0}, True, "RSI 85 超买"),
        ({"rsi": {"rsi": 70}}, {"lbc": 0}, False, "RSI 70 不超买"),
        ({"rsi": None}, {"lbc": 3}, True, "连板3 超买"),
        ({"rsi": None}, {"lbc": 2}, False, "连板2 不超买"),
        ({"rsi": {"rsi": 90}}, {"lbc": 5}, True, "两者均命中"),
        ({"rsi": None}, {"lbc": 0}, False, "均缺失不超买"),
    ]
    for m, s, expect, note in ob_cases:
        got = decision._overbought(m, s)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 超买判定 {note:18s} -> {got} (expect {expect})")
    return fails


def main() -> int:
    fails = 0
    fails += test_stock_sentiment_group()
    fails += test_callback_overbought()
    with tempfile.TemporaryDirectory() as td:
        fails += test_stock_senti_map(Path(td))
    print(f"stock_sentiment: {20 - fails}/20 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
