"""K线形态识别（G8）：8 种高频形态，纯 pandas 实现。

作为决策辅助因子：返回最近识别到的形态列表，供 reason 展示与置信度微调。
"""
import pandas as pd


def _body(o, c):
    return abs(c - o)


def _range(o, h, l, c):
    return max(h, o, c) - min(l, o, c)


def detect(df: pd.DataFrame, lookback: int = 5) -> list:
    """识别最后 lookback 根K线中的形态，返回形态名列表（可空）。"""
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

        # 十字星：实体极小（<振幅 10%）
        if _body(o, c) / rng < 0.1:
            res.append("十字星")
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        down_ctx = close.iloc[i - 1] < close.iloc[i - 2]   # 下跌背景
        up_ctx = close.iloc[i - 1] > close.iloc[i - 2]     # 上涨背景
        # 锤头线：下跌后，下影≥2倍实体，上影短（看涨反转）
        if down_ctx and lower_shadow >= 2 * _body(o, c) and upper_shadow <= _body(o, c):
            res.append("锤头线")
        # 上吊线：上涨后，同锤头形态（看跌反转）
        if up_ctx and _body(o, c) > 0 and lower_shadow >= 2 * _body(o, c) and upper_shadow <= 0.5 * _body(o, c):
            res.append("上吊线")
        # 射击之星：上影≥2倍实体，下影短
        if upper_shadow >= 2 * _body(o, c) and lower_shadow <= _body(o, c):
            res.append("射击之星")
        # 长阳吞没：阳线实体完全覆盖前一根阴线实体
        if c > o and c2 < o2 and c >= o2 and o <= c2:
            res.append("长阳吞没")
        # 早晨之星：长阴+小实体+长阳，第三根收复第一根实体过半
        if _body(o1, c1) / _range(o1, h1, l1, c1) > 0.5 and c1 < o1 and \
                _body(o2, c2) / _range(o2, h2, l2, c2) < 0.1 and \
                c > o and c >= (o1 + c1) / 2:
            res.append("早晨之星")
        # 黄昏之星：长阳+小实体+长阴，第三根跌破第一根实体过半
        if _body(o1, c1) / _range(o1, h1, l1, c1) > 0.5 and c1 > o1 and \
                _body(o2, c2) / _range(o2, h2, l2, c2) < 0.1 and \
                o > c and c <= (o1 + c1) / 2:
            res.append("黄昏之星")
        # 乌云盖顶：阳线后阴线，阴线开盘高于前阳收盘且收盘深入前阳实体
        if c1 > o1 and o > c and o >= c1 and c <= (o1 + c1) / 2:
            res.append("乌云盖顶")
    return list(dict.fromkeys(res))