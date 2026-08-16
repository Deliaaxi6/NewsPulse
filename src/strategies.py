"""经典策略模板（InStock core/strategy 融入）：10 个策略纯 pandas 实现。

判定逻辑逐条对照 InStock 源码（instock/core/strategy/*.py，2023-03 版）转写：
海龟突破/持续上涨/放量上涨/平台突破/回踩年线/高潮跌停/高紧旗形/低波动启动/
无大跌回踩/停机坪。数据不足或行情失败宁缺毋假（返回 False / 空列表），不阻断决策。
行情：新浪日K（net_guard 降级链），≥300 天含成交量，p_change 自行计算。
"""
import pandas as pd

import net_guard

MIN_DAYS = 300
AMOUNT_MIN = 200000000  # 成交额门槛 2 亿（与 InStock 一致）


def fetch_kline(sym: str, asof: str = None):
    """拉取个股日K（新浪，含 volume/amount），计算 p_change。失败返回 None。
    asof 给 'YYYY-MM-DD' 时截断到该日收盘（回测/补跑不含未来数据）。"""
    try:
        import akshare as ak

        prefix = "sh" if sym.startswith("6") else "sz"

        def _sina():
            df = ak.stock_zh_a_daily(symbol=prefix + sym)
            if df is None or df.empty:
                raise ValueError("空行情")
            return df

        df = net_guard.try_chain("新浪日K", [("sina", _sina)])
        df = df.rename(columns=str.lower)
        if "date" in df.columns and asof:
            df = df[df["date"].astype(str).str[:10] <= asof]
        if "p_change" not in df.columns:
            df["p_change"] = (df["close"] / df["close"].shift(1) - 1) * 100
        if "amount" not in df.columns:
            df["amount"] = df["close"] * df["volume"]
        return df.tail(MIN_DAYS).reset_index(drop=True)
    except Exception as e:
        print(f"[warn] {sym} 策略行情失败: {e}")
        return None


def _amount(row):
    return float(row.get("amount", 0) or 0)


# ---------- 1. 海龟突破：收盘 ≥ 前 N 日最高收盘 ----------
def turtle_trade(df, threshold=60):
    if len(df) < threshold:
        return False
    d = df.tail(threshold)
    return float(d.iloc[-1]["close"]) >= float(d["close"].max())


# ---------- 2. 持续上涨：MA30 逐段抬升且涨幅 >20% ----------
def keep_increasing(df, threshold=30):
    if len(df) < threshold:
        return False
    d = df.copy()
    d["ma30"] = d["close"].rolling(30).mean()
    d = d.dropna(subset=["ma30"])
    if len(d) < threshold:
        return False
    d = d.tail(threshold)
    s1, s2 = threshold // 3, threshold * 2 // 3
    return (d.iloc[0]["ma30"] < d.iloc[s1]["ma30"] < d.iloc[s2]["ma30"] < d.iloc[-1]["ma30"]
            and d.iloc[-1]["ma30"] > 1.2 * d.iloc[0]["ma30"])


# ---------- 3. 放量上涨：涨幅≥2%、阳线、成交额≥2亿、量/5日均量≥2 ----------
def enter(df, threshold=60):
    if len(df) < threshold:
        return False
    last = df.iloc[-1]
    if float(last["p_change"]) < 2 or float(last["close"]) <= float(last["open"]):
        return False
    if _amount(last) < AMOUNT_MIN:
        return False
    vol_ma5 = float(df["volume"].iloc[-threshold:-1].tail(5).mean() or 0)
    if vol_ma5 <= 0 or float(last["volume"]) / vol_ma5 < 2:
        return False
    return True


# ---------- 4. 平台突破：放量上穿 MA60，且突破前股价贴近 MA60 ----------
def breakthrough_platform(df, threshold=60):
    if len(df) < threshold:
        return False
    d = df.copy()
    d["ma60"] = d["close"].rolling(60).mean()
    d = d.tail(threshold)
    rows = d.to_dict("records")
    for i in range(len(rows)):
        r = rows[i]
        if r["ma60"] is None or pd.isna(r["ma60"]):
            continue
        if float(r["open"]) < float(r["ma60"]) <= float(r["close"]):
            if _breakout_volume(d, i):
                front = [x for x in rows[:i] if x["ma60"] is not None and not pd.isna(x["ma60"])]
                if front and all(-0.05 < (float(x["ma60"]) - float(x["close"])) / float(x["ma60"]) < 0.2
                                 for x in front):
                    return True
    return False


def _breakout_volume(d, i):
    last = d.iloc[i]
    if float(last["p_change"]) < 2 or float(last["close"]) <= float(last["open"]):
        return False
    if _amount(last) < AMOUNT_MIN:
        return False
    vol_ma5 = float(d["volume"].iloc[:i].tail(5).mean() or 0)
    return vol_ma5 > 0 and float(last["volume"]) / vol_ma5 >= 2


# ---------- 5. 回踩年线：MA250 突破后回踩不破年线、量比>2、回撤<0.8 ----------
def backtrace_ma250(df, threshold=60):
    if len(df) < 250:
        return False
    d = df.copy()
    d["ma250"] = d["close"].rolling(250).mean()
    d = d.dropna(subset=["ma250"])
    if len(d) < threshold:
        return False
    d = d.tail(threshold)
    rows = d.to_dict("records")
    highest, lowest, recent = None, None, None
    for r in rows:
        c, v = float(r["close"]), float(r["volume"])
        if highest is None or c > highest[0]:
            highest = (c, v, r["date"])
        if lowest is None or c < lowest[0]:
            lowest = (c, v, r["date"])
    if not highest or not lowest or highest[1] == 0:
        return False
    hi_idx = next(i for i, r in enumerate(rows) if r["date"] == highest[2])
    front = rows[:hi_idx]
    if not front:
        return False
    if not (float(front[0]["close"]) < float(front[0]["ma250"]) and
            float(front[-1]["close"]) > float(front[-1]["ma250"])):
        return False
    tail_rows = rows[hi_idx:]
    for r in tail_rows:
        if float(r["close"]) < float(r["ma250"]):
            return False
        if recent is None or float(r["close"]) < recent[0]:
            recent = (float(r["close"]), float(r["volume"]), r["date"])
    if not recent:
        return False
    days = (pd.Timestamp(recent[2]) - pd.Timestamp(highest[2])).days
    if not (10 <= days <= 50):
        return False
    if recent[1] <= 0 or highest[1] / recent[1] <= 2:
        return False
    if recent[0] / highest[0] >= 0.8:
        return False
    return True


# ---------- 6. 高潮跌停：跌停、成交额≥2亿、量/5日均量≥4 ----------
def climax_limitdown(df, threshold=60):
    if len(df) < threshold:
        return False
    last = df.iloc[-1]
    if float(last["p_change"]) > -9.5:
        return False
    if _amount(last) < AMOUNT_MIN:
        return False
    vol_ma5 = float(df["volume"].iloc[-threshold:-1].tail(5).mean() or 0)
    return vol_ma5 > 0 and float(last["volume"]) / vol_ma5 >= 4


# ---------- 7. 高紧旗形：强势整理，区间翻倍且含两连板 ----------
def high_tight_flag(df, threshold=60):
    if len(df) < threshold:
        return False
    d = df.tail(threshold)
    seg = d.tail(24).head(14)
    low = float(seg["low"].min())
    if low <= 0 or float(seg.iloc[-1]["high"]) / low < 1.9:
        return False
    prev = 0.0
    for p in seg["p_change"].values:
        p = float(p)
        if p >= 9.5:
            if prev >= 9.5:
                return True
            prev = p
        else:
            prev = 0.0
    return False


# ---------- 8. 低波动启动：近10日平均波幅≤10%且区间振幅>1.1倍 ----------
def low_atr(df, ma_long=250, threshold=10):
    if len(df) < ma_long:
        return False
    d = df.tail(threshold)
    if len(d) < threshold:
        return False
    atr = sum(abs(float(p)) for p in d["p_change"].values) / threshold
    if atr > 10:
        return False
    hi, lo = float(d["close"].max()), float(d["close"].min())
    return lo > 0 and (hi - lo) / lo > 1.1


# ---------- 9. 无大跌回踩：区间涨幅≥60%且无单日/累计大跌洗盘 ----------
def low_backtrace_increase(df, threshold=60):
    if len(df) < threshold:
        return False
    d = df.tail(threshold)
    r0, r1 = float(d.iloc[0]["close"]), float(d.iloc[-1]["close"])
    if r0 <= 0 or (r1 - r0) / r0 < 0.6:
        return False
    prev_p, prev_o = 100.0, -1000000.0
    for _, r in d.iterrows():
        p, c, o = float(r["p_change"]), float(r["close"]), float(r["open"])
        if p < -7 or (c - o) / o * 100 < -7 or prev_p + p < -10 \
                or prev_o > 0 and (c - prev_o) / prev_o * 100 < -10:
            return False
        prev_p, prev_o = p, o
    return True


# ---------- 10. 停机坪：涨停后 3 日横盘（高于涨停价、波幅受限） ----------
def parking_apron(df, threshold=15):
    if len(df) < threshold:
        return False
    d = df.tail(threshold)
    rows = d.to_dict("records")
    offset = len(df) - threshold
    for i, r in enumerate(rows):
        if float(r["p_change"]) <= 9.5:
            continue
        if not turtle_trade(df.iloc[:offset + i + 1], threshold):
            continue
        sub = d.iloc[i + 1:i + 4]
        if len(sub) < 3:
            continue
        lp = float(r["close"])
        d1 = sub.iloc[0]
        if not (float(d1["close"]) > lp and float(d1["open"]) > lp
                and 0.97 < float(d1["close"]) / float(d1["open"]) < 1.03):
            continue
        ok = True
        for _, x in sub.iloc[1:].iterrows():
            if not (0.97 < float(x["close"]) / float(x["open"]) < 1.03
                    and -5 < float(x["p_change"]) < 5
                    and float(x["close"]) > lp and float(x["open"]) > lp):
                ok = False
                break
        if ok:
            return True
    return False


CHECKS = [
    ("海龟突破", turtle_trade),
    ("持续上涨", keep_increasing),
    ("放量上涨", enter),
    ("平台突破", breakthrough_platform),
    ("回踩年线", backtrace_ma250),
    ("高潮跌停", climax_limitdown),
    ("高紧旗形", high_tight_flag),
    ("低波动启动", low_atr),
    ("无大跌回踩", low_backtrace_increase),
    ("停机坪", parking_apron),
]


def detect(sym: str, date_str: str = None) -> list:
    """识别命中 InStock 经典策略的中文名列表（数据不足/行情失败返回 []）。
    date_str 给 'YYYY-MM-DD' 时按该日收盘数据判定（回测/补跑不含未来数据）。"""
    df = fetch_kline(sym, asof=date_str)
    if df is None or len(df) < 30:
        return []
    return [name for name, fn in CHECKS if fn(df)]
