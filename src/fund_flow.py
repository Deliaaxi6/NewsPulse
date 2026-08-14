"""G6 资金面因子：两融余额趋势 + 北向资金（已停发则降级）。

数据源 adata（1nchaos/adata）：
- sentiment.securities_margin(start_date=...)：两融余额（需带日期参数，否则空）
- sentiment.north.north_flow()：北向资金净买入（2024-08 起已停止披露，全 0 视为不可用）
- stock.info.trade_calendar()：交易日历（trade_status 1=开市 0=休市）

设计原则（与 G8 一致）：辅助因子不改买卖主规则，仅微调 confidence 与 reason；
数据缺失/不可用 → 宁缺毋假，返回 0 加成并标注原因，绝不抛异常阻断主流程。
"""
import datetime as dt

import pandas as pd


def get_trade_calendar() -> pd.DataFrame | None:
    """交易日历 → DataFrame[trade_date, is_open]。失败返回 None。"""
    try:
        import adata
        df = adata.stock.info.trade_calendar()
        if df is None or df.empty or "trade_status" not in df.columns:
            return None
        out = pd.DataFrame({
            "trade_date": pd.to_datetime(df["trade_date"]).dt.date,
            "is_open": df["trade_status"].astype(int) == 1,
        })
        return out
    except Exception as e:
        print(f"[warn] 交易日历获取失败: {e}")
        return None


def is_trading_day(date_str: str, cal: pd.DataFrame | None = None) -> bool | None:
    """date_str 是否为开市日。日历不可用返回 None（不阻断调用方）。"""
    cal = cal if cal is not None else get_trade_calendar()
    if cal is None or cal.empty or "trade_date" not in cal.columns:
        return None
    d = dt.date.fromisoformat(date_str)
    hit = cal[cal["trade_date"] == d]
    if hit.empty or "is_open" not in hit.columns:
        return None
    return bool(hit.iloc[0]["is_open"])


def trading_days_between(start: str, end: str,
                         cal: pd.DataFrame | None = None) -> int | None:
    """[start, end] 区间内开市日数量（含两端）。日历不可用返回 None（fail-open）。"""
    cal = cal if cal is not None else get_trade_calendar()
    if cal is None or cal.empty or "trade_date" not in cal.columns or "is_open" not in cal.columns:
        return None
    a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if b < a:
        a, b = b, a
    sub = cal[(cal["trade_date"] >= a) & (cal["trade_date"] <= b)]
    return int(sub["is_open"].sum())


def fetch_margin(start_date: str | None = None) -> pd.DataFrame | None:
    """两融余额（东财披露滞后约一周）。失败/空返回 None。"""
    try:
        import adata
        kwargs = {"start_date": start_date} if start_date else {}
        df = adata.sentiment.securities_margin(**kwargs)
        if df is None or df.empty:
            return None
        out = pd.DataFrame({
            "trade_date": pd.to_datetime(df["trade_date"]).dt.date,
            "rzrqye": pd.to_numeric(df["rzrqye"], errors="coerce"),
        }).sort_values("trade_date").reset_index(drop=True)
        return out.dropna()
    except Exception as e:
        print(f"[warn] 两融余额获取失败: {e}")
        return None


def fetch_north_flow() -> pd.DataFrame | None:
    """北向资金净买入。2024-08 起官方停发每日数据，全 0/空 → None（宁缺毋假）。"""
    try:
        import adata
        df = adata.sentiment.north.north_flow()
        if df is None or df.empty or "net_tgt" not in df.columns:
            return None
        if pd.to_numeric(df["net_tgt"], errors="coerce").abs().sum() == 0:
            return None
        out = pd.DataFrame({
            "trade_date": pd.to_datetime(df["trade_date"]).dt.date,
            "net_tgt": pd.to_numeric(df["net_tgt"], errors="coerce"),
        }).sort_values("trade_date").reset_index(drop=True)
        return out.dropna()
    except Exception as e:
        print(f"[warn] 北向资金获取失败: {e}")
        return None


def margin_trend(df: pd.DataFrame | None, half=5, thr=0.01) -> dict:
    """两融余额趋势：近 half 日均值 vs 前 half 日均值。

    df: DataFrame[trade_date, rzrqye]（升序）。返回 {"dir", "pct", "label"}；
    数据不足（<2*half）→ dir=unavailable。
    """
    if df is None or len(df) < 2 * half:
        return {"dir": "unavailable", "pct": float("nan"), "label": "两融数据不足"}
    recent = df["rzrqye"].iloc[-half:].mean()
    prev = df["rzrqye"].iloc[-2 * half:-half].mean()
    if prev <= 0:
        return {"dir": "unavailable", "pct": float("nan"), "label": "两融基期异常"}
    pct = (recent - prev) / prev
    if pct > thr:
        d = "expand"
        label = f"两融余额回升{pct:+.2%}"
    elif pct < -thr:
        d = "shrink"
        label = f"两融余额回落{pct:+.2%}"
    else:
        d = "flat"
        label = f"两融余额平稳{pct:+.2%}"
    return {"dir": d, "pct": round(float(pct), 6), "label": label}


def north_signal(df: pd.DataFrame | None) -> dict:
    """北向资金信号：最近一日净买入方向。不可用 → unavailable。"""
    if df is None or df.empty:
        return {"dir": "unavailable", "label": "北向资金不可用（2024-08 起官方停发每日数据）"}
    latest = float(df["net_tgt"].iloc[-1])
    if latest > 0:
        return {"dir": "inflow", "label": f"北向净流入{latest:.0f}万"}
    return {"dir": "outflow", "label": f"北向净流出{abs(latest):.0f}万"}


def fund_factor(date_str: str | None = None, margin_df: pd.DataFrame | None = None,
                north_df: pd.DataFrame | None = None) -> dict:
    """资金面辅助因子（G6）：微调 confidence（±0.05）并生成 reason 摘要。

    conf=0 且全部数据不可用时不报错、不阻断。返回
    {"conf": float, "label": str, "unavailable": [str]}
    """
    if date_str:
        start = (dt.date.fromisoformat(date_str) - dt.timedelta(days=30)).isoformat()
    else:
        start = None
    margin_df = margin_df if margin_df is not None else fetch_margin(start)
    north_df = north_df if north_df is not None else fetch_north_flow()

    unavailable = []
    conf_parts = []
    labels = []

    mt = margin_trend(margin_df)
    if mt["dir"] == "expand":
        conf_parts.append(0.05)
        labels.append(mt["label"])
    elif mt["dir"] == "shrink":
        conf_parts.append(-0.05)
        labels.append(mt["label"])
    elif mt["dir"] == "unavailable":
        unavailable.append(mt["label"])

    ns = north_signal(north_df)
    if ns["dir"] == "inflow":
        conf_parts.append(0.05)
        labels.append(ns["label"])
    elif ns["dir"] == "outflow":
        conf_parts.append(-0.05)
        labels.append(ns["label"])
    else:
        unavailable.append(ns["label"])

    conf = min(0.1, max(-0.1, sum(conf_parts))) if conf_parts else 0.0
    label = "; ".join(labels) if labels else ""
    if unavailable:
        label = (label + "; " if label else "") + "资金面部分数据缺失跳过"
    return {"conf": round(conf, 4), "label": label, "unavailable": unavailable}