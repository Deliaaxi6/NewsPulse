"""筹码分布（CYQ，InStock 融入）：每日成交量按三角形分布到 [最低价,最高价]，
历史筹码逐日衰减，输出获利盘比例/平均成本/集中度。

仅供报告展示，不参与决策。宁缺毋假：数据不足或失败返回 None。
"""
import pandas as pd
import numpy as np

from config import sina_prefix


def fetch_daily(symbol: str, days: int = 180) -> pd.DataFrame:
    """拉取历史日K（新浪，含成交量），升序。失败返回空表。"""
    import akshare as ak
    df = ak.stock_zh_a_daily(symbol=sina_prefix(symbol) + symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.tail(days).reset_index(drop=True)
    df["date"] = df["date"].astype(str).str[:10]
    return df[["date", "open", "high", "low", "close", "volume"]]


def _tri_w(n, k):
    """三角形权重：区间中位价权重最大，两端最小（≥0.05 防除零）。k∈[0,n-1]。"""
    c = (n - 1) / 2.0
    return max(1 - abs(k - c) / (c + 1e-9), 0.05)


def cyq(df: pd.DataFrame, bins: int = 120, decay: float = 0.9,
        min_rows: int = 30) -> dict | None:
    """筹码分布计算。

    df: DataFrame[date, high, low, close, volume]（升序）。
    返回 {"dist", "grid", "winner", "avg_cost", "concentration", "last_close", "days"}；
    数据不足/异常返回 None。
    """
    if df is None or len(df) < min_rows or not {"high", "low", "close", "volume"}.issubset(df.columns):
        return None
    lo = float(df["low"].min())
    hi = float(df["high"].max())
    if not (hi > lo):
        return None
    grid = np.linspace(lo, hi, bins)
    width = grid[1] - grid[0]
    total = np.zeros(bins)
    for _, r in df.iterrows():
        h, l, v = float(r["high"]), float(r["low"]), float(r["volume"])
        if v <= 0 or h < l:
            continue
        i0 = int((l - lo) / width)
        i1 = int((h - lo) / width)
        i0 = max(0, min(bins - 1, i0))
        i1 = max(0, min(bins - 1, i1))
        n = i1 - i0 + 1
        ws = np.array([_tri_w(n, k) for k in range(n)])
        ws = ws / ws.sum() * v
        total = total * decay
        total[i0:i1 + 1] += ws
    s = float(total.sum())
    if s <= 0:
        return None
    dist = total / s
    last_close = float(df["close"].iloc[-1])
    winner = float(dist[grid <= last_close].sum())
    avg_cost = float((grid * dist).sum())
    cum = np.cumsum(dist)
    p5 = float(grid[np.searchsorted(cum, 0.05)])
    p95 = float(grid[np.searchsorted(cum, 0.95)])
    concentration = (p95 - p5) / avg_cost if avg_cost > 0 else float("nan")
    return {"dist": dist, "grid": grid, "winner": winner,
            "avg_cost": round(avg_cost, 2),
            "concentration": round(float(concentration), 4),
            "last_close": round(last_close, 2), "days": len(df)}


def summarize(res: dict | None) -> str:
    """可读摘要（报告展示）。"""
    if res is None:
        return "筹码分布: 数据不足/不可用"
    return (f"获利盘{res['winner']:.0%}，平均成本{res['avg_cost']:.2f}，"
            f"集中度{res['concentration']:.1%}（90%筹码区间/均价），"
            f"现价{res['last_close']:.2f}")