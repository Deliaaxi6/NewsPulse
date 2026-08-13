"""技术指标模块（G8）：MA / MACD / KDJ / RSI / BOLL，纯 pandas 实现，无 talib 依赖。

作为 decision.py 的辅助因子使用：数据不足或失败时返回 None，宁缺毋假，不影响主决策。
"""
import pandas as pd


def fetch_daily(symbol: str, days: int = 120) -> pd.DataFrame:
    """拉取历史日K（新浪），返回升序 DataFrame[date, open, high, low, close]。失败返回空表。"""
    import akshare as ak
    prefix = "sh" if symbol.startswith("6") else "sz"
    df = ak.stock_zh_a_daily(symbol=prefix + symbol)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    df = df.tail(days).reset_index(drop=True)
    df["date"] = df["date"].astype(str).str[:10]
    return df[["date", "open", "high", "low", "close"]]


def ma(close: pd.Series, n: int) -> float:
    if len(close) < n:
        return None
    return float(close.rolling(n).mean().iloc[-1])


def macd(close: pd.Series, fast=12, slow=26, signal=9) -> dict:
    """返回最新 DIF/DEA/柱 及是否金叉（DIF 上穿 DEA，仅当日）。"""
    if len(close) < slow + signal:
        return None
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    dif_v, dea_v = float(dif.iloc[-1]), float(dea.iloc[-1])
    golden = dif_v > dea_v and float(dif.iloc[-2]) <= float(dea.iloc[-2])
    death = dif_v < dea_v and float(dif.iloc[-2]) >= float(dea.iloc[-2])
    return {"dif": dif_v, "dea": dea_v, "hist": dif_v - dea_v,
            "golden_cross": golden, "death_cross": death,
            "above_zero": dif_v > 0 and dea_v > 0}


def kdj(df: pd.DataFrame, n=9, m1=3, m2=3) -> dict:
    """KDJ：返回最新 K/D/J 与超买超卖状态。"""
    if len(df) < n:
        return None
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, float("nan")) * 100
    rsv = rsv.fillna(50.0)
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    k_v, d_v, j_v = float(k.iloc[-1]), float(d.iloc[-1]), float(j.iloc[-1])
    return {"k": k_v, "d": d_v, "j": j_v,
            "golden_cross": k_v > d_v and float(k.iloc[-2]) <= float(d.iloc[-2]),
            "overbought": k_v > 80, "oversold": k_v < 20}


def rsi(close: pd.Series, n=14) -> dict:
    """RSI：返回最新 RSI 与超买超卖状态。纯上涨→100，纯下跌→0。"""
    if len(close) <= n:
        return None
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
    if g == 0 and l == 0:
        value = 50.0
    elif l == 0:
        value = 100.0
    elif g == 0:
        value = 0.0
    else:
        value = 100 - 100 / (1 + g / l)
    return {"rsi": value, "overbought": value > 70, "oversold": value < 30}


def boll(close: pd.Series, n=20, k=2) -> dict:
    """BOLL：返回最新中/上/下轨与突破状态。"""
    if len(close) < n:
        return None
    mid = close.rolling(n).mean()
    std = close.rolling(n).std(ddof=0)
    upper, lower = mid + k * std, mid - k * std
    c = float(close.iloc[-1])
    return {"mid": float(mid.iloc[-1]), "upper": float(upper.iloc[-1]),
            "lower": float(lower.iloc[-1]), "break_upper": c > float(upper.iloc[-1]),
            "break_lower": c < float(lower.iloc[-1])}


def analyze(df: pd.DataFrame) -> dict:
    """汇总五指标状态，供决策辅助。数据不足时字段为 None。"""
    if df is None or df.empty or len(df) < 30:
        return {"ok": False, "reason": "行情不足30日，辅助因子跳过"}
    close = df["close"]
    m = {}
    m["ma5"], m["ma20"], m["ma60"] = ma(close, 5), ma(close, 20), ma(close, 60)
    m["ma_bullish"] = None
    if all(v is not None for v in (m["ma5"], m["ma20"], m["ma60"])):
        m["ma_bullish"] = m["ma5"] > m["ma20"] > m["ma60"]
    m["macd"] = macd(close)
    m["kdj"] = kdj(df)
    m["rsi"] = rsi(close)
    m["boll"] = boll(close)
    m["ok"] = True
    return m


def describe(m: dict) -> str:
    """辅助因子的可读摘要（追加到 reason 末尾）。"""
    if not m.get("ok"):
        return f"技术面: {m.get('reason', '跳过')}"
    parts = []
    if m["ma_bullish"] is True:
        parts.append("均线多头排列")
    if m["macd"] and m["macd"]["golden_cross"]:
        parts.append("MACD金叉")
    if m["macd"] and m["macd"]["above_zero"]:
        parts.append("MACD零轴上")
    if m["kdj"] and m["kdj"]["overbought"]:
        parts.append("KDJ超买")
    if m["kdj"] and m["kdj"]["oversold"]:
        parts.append("KDJ超卖")
    if m["rsi"] and m["rsi"]["overbought"]:
        parts.append("RSI超买")
    if m["rsi"] and m["rsi"]["oversold"]:
        parts.append("RSI超卖")
    if m["boll"] and m["boll"]["break_upper"]:
        parts.append("突破布林上轨")
    if not parts:
        parts.append("中性")
    return "技术面: " + "/".join(parts)