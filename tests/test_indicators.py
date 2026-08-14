"""技术指标 + K线形态测试（G8）：构造确定性数据验证，边界覆盖。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import indicators
import kline_patterns


def _ohlc(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])


def _flat(n=80, base=10.0):
    """恒定收盘序列：无趋势，保证数据量足够且形态无噪声。"""
    import datetime as dt
    return _ohlc([(dt.date(2026, 1, 1) + dt.timedelta(days=i), base, base + 0.01,
                   base - 0.01, base) for i in range(n)])


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # --- 指标：恒定序列，MA=base，RSI 中性≈50，MACD 零轴附近 ---
    df = _flat()
    close = df["close"]
    check("MA5=base", indicators.ma(close, 5) == 10.0)
    check("MA不足返回None", indicators.ma(close[:3], 5) is None)
    macd_v = indicators.macd(close)
    check("MACD返回字段", macd_v and "golden_cross" in macd_v)
    rsi_v = indicators.rsi(close)
    check("RSI恒定≈50", rsi_v and 49 < rsi_v["rsi"] < 51, f"rsi={rsi_v['rsi']:.1f}")
    kdj_v = indicators.kdj(df)
    check("KDJ恒定≈50", kdj_v and 40 < kdj_v["k"] < 60, f"k={kdj_v['k']:.1f}")
    boll_v = indicators.boll(close)
    check("BOLL中轨=base", boll_v and abs(boll_v["mid"] - 10.0) < 1e-9)
    check("分析汇总ok", indicators.analyze(df).get("ok") is True)
    check("数据不足ok=False", indicators.analyze(df[:10]).get("ok") is False)

    # --- 指标：构造明确超买（连续涨停式上涨）--- 
    import datetime as dt
    up_rows = []
    c = 10.0
    for i in range(40):
        c = c * 1.03
        up_rows.append((dt.date(2026, 2, 1) + dt.timedelta(days=i), c * 0.995,
                        c * 1.01, c * 0.99, c))
    rsi_up = indicators.rsi(_ohlc(up_rows)["close"])
    check("连续上涨RSI超买", rsi_up and rsi_up["overbought"] is True,
          f"rsi={rsi_up['rsi']:.1f}" if rsi_up else "")

    # --- 形态：构造锤头线（talib 0.6.4：实体<前10根实体均值、长下影、
    # 短上影、实体贴近前一日低点；前置窄幅阴线 + 尾根长下影）---
    import datetime as dt2
    hammer_rows = []
    for i in range(11):
        o, h, l, c = 100 - 0.1 * i, 100.2 - 0.1 * i, 99.2 - 0.1 * i, 99.5 - 0.1 * i
        hammer_rows.append((dt2.date(2026, 3, 1) + dt2.timedelta(days=i),
                            o, h, l, c))
    hammer_rows.append((dt2.date(2026, 3, 12), 98.2, 98.55, 93.2, 98.5))
    pats = kline_patterns.detect(_ohlc(hammer_rows))
    check("锤头线识别", "锤头" in pats, str(pats))

    # --- 形态：构造十字星（极窄实体的尾根，talib 判为长脚十字/十字）---
    doji_rows = []
    for i in range(15):
        doji_rows.append((dt2.date(2026, 3, 1) + dt2.timedelta(days=i),
                          100.0, 100.5, 99.5, 100.0))
    last = doji_rows[-1]
    doji_rows.append((last[0], 100.0, 100.6, 99.5, 100.02))  # 实体0.02/振幅1.1
    pats = kline_patterns.detect(_ohlc(doji_rows))
    check("十字星识别", "十字" in pats and "长脚十字" in pats, str(pats))

    # --- 形态：空表与短序列边界 ---
    check("空表返回[]", kline_patterns.detect(pd.DataFrame()) == [])
    check("短序列返回[]", kline_patterns.detect(_ohlc([(1, 1, 1, 1, 1)])) == [])

    # --- analyze 对平盘行情无超买误报 ---
    m_flat = indicators.analyze(df)
    check("平盘无超买误报",
          not (m_flat["kdj"]["overbought"] or m_flat["rsi"]["overbought"]))
    print(f"indicators: {16 - fails + 0}/16 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())