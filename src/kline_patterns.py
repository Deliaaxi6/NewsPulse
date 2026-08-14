"""K线形态识别（G8 扩展，InStock 融入）：talib 61 种 CDL 形态全量识别。

- 首选引擎：pandas-ta 的 cdl_pattern(name='all')，经 TA-Lib C 库输出全部
  61 种形态（与 InStock 同引擎、同名，中文名取自 InStock tablestructure.py）；
- 降级引擎：TA-Lib 未安装时回退纯 pandas 8 种高频形态（_detect_legacy），
  宁缺毋假不伪装。
作为决策辅助因子：返回最近 lookback 根K线中识别到的形态中文名列表。
"""
import pandas as pd

# talib 形态英文列名 → 中文名（与 InStock cn 字段一致）
TALIB_CN_MAP = {
    "CDL_2CROWS": "两只乌鸦",
    "CDL_UPSIDEGAP2CROWS": "向上跳空的两只乌鸦",
    "CDL_3BLACKCROWS": "三只乌鸦",
    "CDL_IDENTICAL3CROWS": "三胞胎乌鸦",
    "CDL_3LINESTRIKE": "三线打击",
    "CDL_DARKCLOUDCOVER": "乌云压顶",
    "CDL_EVENINGDOJISTAR": "十字暮星",
    "CDL_DOJISTAR": "十字星",
    "CDL_HANGINGMAN": "上吊线",
    "CDL_HIKKAKE": "陷阱",
    "CDL_HIKKAKEMOD": "修正陷阱",
    "CDL_INNECK": "颈内线",
    "CDL_ONNECK": "颈上线",
    "CDL_THRUSTING": "插入",
    "CDL_SHOOTINGSTAR": "射击之星",
    "CDL_STALLEDPATTERN": "停顿形态",
    "CDL_ADVANCEBLOCK": "大敌当前",
    "CDL_HIGHWAVE": "风高浪大线",
    "CDL_ENGULFING": "吞噬模式",
    "CDL_ABANDONEDBABY": "弃婴",
    "CDL_CLOSINGMARUBOZU": "收盘缺影线",
    "CDL_DOJI": "十字",
    "CDL_DOJI_10_0.1": "十字",
    "CDL_GAPSIDESIDEWHITE": "向上/下跳空并列阳线",
    "CDL_LONGLEGGEDDOJI": "长脚十字",
    "CDL_RICKSHAWMAN": "黄包车夫",
    "CDL_MARUBOZU": "光头光脚/缺影线",
    "CDL_3INSIDE": "三内部上涨和下跌",
    "CDL_3OUTSIDE": "三外部上涨和下跌",
    "CDL_3STARSINSOUTH": "南方三星",
    "CDL_3WHITESOLDIERS": "三个白兵",
    "CDL_BELTHOLD": "捉腰带线",
    "CDL_BREAKAWAY": "脱离",
    "CDL_CONCEALBABYSWALL": "藏婴吞没",
    "CDL_COUNTERATTACK": "反击线",
    "CDL_DRAGONFLYDOJI": "蜻蜓十字/T形十字",
    "CDL_EVENINGSTAR": "暮星",
    "CDL_GRAVESTONEDOJI": "墓碑十字/倒T十字",
    "CDL_HAMMER": "锤头",
    "CDL_HARAMI": "母子线",
    "CDL_INSIDE": "母子线",
    "CDL_HARAMICROSS": "十字孕线",
    "CDL_HOMINGPIGEON": "家鸽",
    "CDL_INVERTEDHAMMER": "倒锤头",
    "CDL_KICKING": "反冲形态",
    "CDL_KICKINGBYLENGTH": "由较长缺影线决定的反冲形态",
    "CDL_LADDERBOTTOM": "梯底",
    "CDL_LONGLINE": "长蜡烛",
    "CDL_MATCHINGLOW": "相同低价",
    "CDL_MATHOLD": "铺垫",
    "CDL_MORNINGDOJISTAR": "十字晨星",
    "CDL_MORNINGSTAR": "晨星",
    "CDL_PIERCING": "刺透形态",
    "CDL_RISEFALL3METHODS": "上升/下降三法",
    "CDL_SEPARATINGLINES": "分离线",
    "CDL_SHORTLINE": "短蜡烛",
    "CDL_SPINNINGTOP": "纺锤",
    "CDL_STICKSANDWICH": "条形三明治",
    "CDL_TAKURI": "探水竿",
    "CDL_TASUKIGAP": "跳空并列阴阳线",
    "CDL_TRISTAR": "三星",
    "CDL_UNIQUE3RIVER": "奇特三河床",
    "CDL_XSIDEGAP3METHODS": "上升/下降跳空三法",
}


def _body(o, c):
    return abs(c - o)


def _range(o, h, l, c):
    return max(h, o, c) - min(l, o, c)


def _detect_legacy(df: pd.DataFrame, lookback: int = 5) -> list:
    """降级引擎：纯 pandas 8 种高频形态（TA-Lib 不可用时）。"""
    if df is None or df.empty or len(df) < 3:
        return []
    res = []
    close = df["close"]
    for i in range(max(0, len(df) - lookback), len(df)):
        if i < 2:
            continue
        o1, h1, l1, c1 = df["open"].iloc[i - 2], df["high"].iloc[i - 2], df["low"].iloc[i - 2], df["close"].iloc[i - 2]
        o2, h2, l2, c2 = df["open"].iloc[i - 1], df["high"].iloc[i - 1], df["low"].iloc[i - 1], df["close"].iloc[i - 1]
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        rng = _range(o, h, l, c)
        if rng <= 0:
            continue
        if _body(o, c) / rng < 0.1:
            res.append("十字星")
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        down_ctx = close.iloc[i - 1] < close.iloc[i - 2]
        up_ctx = close.iloc[i - 1] > close.iloc[i - 2]
        if down_ctx and lower_shadow >= 2 * _body(o, c) and upper_shadow <= _body(o, c):
            res.append("锤头线")
        if up_ctx and _body(o, c) > 0 and lower_shadow >= 2 * _body(o, c) and upper_shadow <= 0.5 * _body(o, c):
            res.append("上吊线")
        if upper_shadow >= 2 * _body(o, c) and lower_shadow <= _body(o, c):
            res.append("射击之星")
        if c > o and c2 < o2 and c >= o2 and o <= c2:
            res.append("长阳吞没")
        if _body(o1, c1) / _range(o1, h1, l1, c1) > 0.5 and c1 < o1 and \
                _body(o2, c2) / _range(o2, h2, l2, c2) < 0.1 and \
                c > o and c >= (o1 + c1) / 2:
            res.append("早晨之星")
        if _body(o1, c1) / _range(o1, h1, l1, c1) > 0.5 and c1 > o1 and \
                _body(o2, c2) / _range(o2, h2, l2, c2) < 0.1 and \
                o > c and c <= (o1 + c1) / 2:
            res.append("黄昏之星")
        if c1 > o1 and o > c and o >= c1 and c <= (o1 + c1) / 2:
            res.append("乌云压顶")
    return list(dict.fromkeys(res))


def _detect_talib(df: pd.DataFrame, lookback: int = 5) -> list:
    """talib 引擎：61 种 CDL 形态全量识别，返回中文名列表。"""
    import pandas_ta as pta

    r = df.ta.cdl_pattern(name="all")
    if r is None or r.empty:
        return []
    hits = []
    for col in r.columns:
        s = r[col]
        tail = s.tail(lookback)
        if (tail.notna() & (tail != 0)).any():
            hits.append(TALIB_CN_MAP.get(col, col))
    return list(dict.fromkeys(hits))


def detect(df: pd.DataFrame, lookback: int = 5) -> list:
    """识别最后 lookback 根K线中的形态，返回形态中文名列表（可空）。

    TA-Lib 可用 → 61 种全量；不可用 → 纯 pandas 8 种降级。
    """
    if df is None or df.empty or len(df) < 3:
        return []
    try:
        return _detect_talib(df, lookback)
    except Exception as e:
        print(f"[warn] TA-Lib 形态识别不可用，降级纯 pandas 8 种: {e}")
        return _detect_legacy(df, lookback)