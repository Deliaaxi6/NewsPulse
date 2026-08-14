"""综合选股测试（InStock 融入）：涨停池→策略扫描→观察池 CSV 的确定性用例。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pandas as pd

import select_stock
from config import DATA_DIR

TEST_DATE = "2099-01-01"


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    out = DATA_DIR / f"select_{TEST_DATE}.csv"
    if out.exists():
        out.unlink()
    select_stock.fund_flow.is_trading_day = lambda d: True
    orig_pool, orig_detect = select_stock._zt_pool, select_stock.strategies.detect

    # --- 正常：3 只涨停池 → 连板降序排序 + detect 命中写入 ---
    pool = pd.DataFrame([
        {"代码": "600519", "名称": "贵州茅台", "连板数": 1, "封板资金": 5e8},
        {"代码": "000858", "名称": "五粮液", "连板数": 3, "封板资金": 1e8},
        {"代码": "601318", "名称": "中国平安", "连板数": 2, "封板资金": 3e8},
    ])
    hits = {"600519": ["海龟突破"], "000858": [], "601318": ["平台突破", "放量上涨"]}
    select_stock._zt_pool = lambda base: pool
    select_stock.strategies.detect = lambda sym: list(hits.get(sym, []))
    select_stock.select(TEST_DATE)
    check("CSV 已写入", out.exists())
    df = pd.read_csv(out, encoding="utf-8-sig", dtype={"symbol": str})
    check("连板数降序", list(df["symbol"]) == ["000858", "601318", "600519"])
    check("code 格式（深）", df.iloc[0]["code"] == "000858.XSHE")
    check("code 格式（沪）", df.iloc[1]["code"] == "601318.XSHG")
    check("未命中 score=0", df.iloc[0]["score"] == 0)
    check("命中策略分号连接", df.iloc[1]["strategies"] == "平台突破;放量上涨" and df.iloc[1]["score"] == 2)
    check("lbc/seal_amount 保留", int(df.iloc[0]["lbc"]) == 3 and float(df.iloc[0]["seal_amount"]) == 1e8)
    rows = select_stock.load_pool(TEST_DATE)
    check("load_pool 读回结构", len(rows) == 3 and rows[0]["symbol"] == "000858")
    check("load_pool 前导0保留", rows[0]["code"] == "000858.XSHE")
    check("load_pool 空策略填空串", rows[0]["strategies"] == "")

    # --- MAX_SCAN 截断 ---
    big = pd.DataFrame([
        {"代码": f"60{i:04d}", "名称": f"股{i}", "连板数": 1, "封板资金": 1e8}
        for i in range(25)
    ])
    select_stock._zt_pool = lambda base: big
    select_stock.strategies.detect = lambda sym: []
    select_stock.select(TEST_DATE)
    df = pd.read_csv(out, encoding="utf-8-sig")
    check("MAX_SCAN 截断", len(df) == 20)

    # --- 涨停池为空 → fail-open 写空 CSV ---
    select_stock._zt_pool = lambda base: pd.DataFrame()
    select_stock.select(TEST_DATE)
    df = pd.read_csv(out, encoding="utf-8-sig")
    check("空池写空 CSV", df.empty)
    check("空池 load_pool 返回 []", select_stock.load_pool(TEST_DATE) == [])

    # --- 涨停池接口异常 → fail-open ---
    select_stock._zt_pool = lambda base: (_ for _ in ()).throw(ConnectionError("boom"))
    select_stock.select(TEST_DATE)
    df = pd.read_csv(out, encoding="utf-8-sig")
    check("接口异常写空 CSV", df.empty)

    # --- 非交易日 → 不写文件 ---
    select_stock.fund_flow.is_trading_day = lambda d: False
    out.unlink()
    select_stock.select(TEST_DATE)
    check("非交易日跳过不写", not out.exists())

    # --- load_pool 文件不存在 → [] ---
    check("load_pool 缺文件返回 []", select_stock.load_pool("2099-06-06") == [])

    select_stock._zt_pool, select_stock.strategies.detect = orig_pool, orig_detect
    select_stock.fund_flow.is_trading_day = lambda d: None
    if out.exists():
        out.unlink()
    print("\nselect_stock tests done.")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)