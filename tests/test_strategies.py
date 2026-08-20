"""经典策略模板测试：10 个 InStock 转写策略的命中/未命中/边界用例。"""
import sys
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import strategies as S
from config import sina_prefix


def _kline(closes, volumes=None, opens=None):
    n = len(closes)
    closes = [float(c) for c in closes]
    volumes = volumes or [1e6] * n
    opens = opens or [c * 0.998 for c in closes]
    highs = [max(o, c) * 1.005 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.995 for o, c in zip(opens, closes)]
    dates = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    df = pd.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows,
                       "close": closes, "volume": volumes})
    df["amount"] = df["close"] * df["volume"]
    df["p_change"] = (df["close"] / df["close"].shift(1) - 1) * 100
    df.loc[0, "p_change"] = 0.0
    return df


def main() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name}")

    # 1 海龟突破：60天单调跌，末日创新高
    d = _kline([100 - i * 0.5 for i in range(59)] + [105])
    check("turtle_hit 末日创新高", S.turtle_trade(d))
    check("turtle_miss 末日未新高", not S.turtle_trade(_kline([100 - i * 0.5 for i in range(59)] + [90])))

    # 2 持续上涨：60天 100->160 ma30 抬升>20%
    check("keepinc_hit", S.keep_increasing(_kline([100 + i for i in range(60)])))
    check("keepinc_miss 涨幅不足", not S.keep_increasing(_kline([100 + 0.1 * i for i in range(60)])))

    # 3 放量上涨
    check("enter_hit", S.enter(_kline([100] * 59 + [103], [1e6] * 59 + [3e6], [100] * 59 + [101])))
    check("enter_miss 涨幅1%", not S.enter(_kline([100] * 59 + [101], [1e6] * 59 + [3e6], [100] * 59 + [100.5])))
    check("enter_miss 量比不足", not S.enter(_kline([100] * 59 + [103], [1e6] * 59 + [1.2e6], [100] * 59 + [101])))

    # 4 平台突破
    check("breakthrough_hit", S.breakthrough_platform(_kline([100] * 119 + [102], [1e6] * 119 + [3e6], [100] * 119 + [98])))
    check("breakthrough_miss 无量", not S.breakthrough_platform(_kline([100] * 119 + [102], [1e6] * 120, [100] * 119 + [98])))

    # 5 回踩年线：250天缓涨(80->100)+40天下杀(100->70)+60天反弹(70->122)+顶部+回踩(96)
    c = list(np.linspace(80, 100, 250))
    c += list(np.linspace(100, 70, 40))[1:]
    c += list(np.linspace(70, 122, 60))[1:]
    c += [122.0] * 5
    c += list(np.linspace(122, 96, 12))[1:]
    v = [1e6] * len(c)
    v[250 + 39 + 59 - 1] = 6e6
    check("ma250_hit 回踩不破年线", S.backtrace_ma250(_kline(c, v)))

    # 6 高潮跌停
    check("climax_hit", S.climax_limitdown(_kline([100] * 59 + [90], [1e6] * 59 + [4e6])))
    check("climax_miss 未跌停", not S.climax_limitdown(_kline([100] * 59 + [96], [1e6] * 59 + [4e6])))

    # 7 高紧旗形：seg 内低点55 + 翻倍 + 两连板
    c = [100] * 60
    c[36] = 55
    for i in range(37, 44):
        c[i] = c[i - 1] + (90 - 55) / 7
    c[44] = 99.0
    c[45] = 108.9
    c[46] = c[47] = c[48] = c[49] = 108.9
    check("htf_hit", S.high_tight_flag(_kline(c)))
    check("htf_miss 区间未翻倍", not S.high_tight_flag(_kline([100] * 60)))

    # 8 低波动启动：平盘+4天连涨22.5% (atr=9<10, 振幅>1.1)
    c = [100] * 240 + [95.0] * 6
    x = 95.0
    for _ in range(4):
        x *= 1.225
        c.append(x)
    check("lowatr_hit", S.low_atr(_kline(c)))
    check("lowatr_miss 振幅不足", not S.low_atr(_kline([100] * 240 + list(np.linspace(95, 150, 10)))))

    # 9 无大跌回踩
    check("lowbt_hit", S.low_backtrace_increase(_kline(list(np.linspace(100, 170, 60)))))
    c = list(np.linspace(100, 170, 60))
    c[40] = c[39] * 0.92
    check("lowbt_miss 单日-8%", not S.low_backtrace_increase(_kline(c)))

    # 10 停机坪：16天平盘+涨停110+3天横盘
    c = [100] * 16 + [110, 111, 110.5, 111]
    o = [100] * 16 + [108, 110.5, 111, 110.5]
    check("apron_hit", S.parking_apron(_kline(c, [1e6] * 20, o)))

    # 11 边界：数据不足均 False
    short = _kline([100] * 10)
    for name, fn in S.CHECKS:
        check(f"short_df {name}", not fn(short))

    # 12 空值边界：volume 缺失列不崩溃（turtle 仅依赖 close，平盘末日=最高为 True）
    no_vol = _kline([100] * 60).drop(columns=["volume"])
    check("vol缺失列 turtle 不崩溃", S.turtle_trade(no_vol))

    # 13 行情前缀（北交所 bj 支持）
    check("sina_prefix 沪", sina_prefix("600519") == "sh")
    check("sina_prefix 科创", sina_prefix("688836") == "sh")
    check("sina_prefix 深", sina_prefix("000858") == "sz")
    check("sina_prefix 创业", sina_prefix("300750") == "sz")
    check("sina_prefix 北交920", sina_prefix("920001") == "bj")
    check("sina_prefix 北交8", sina_prefix("833171") == "bj")
    check("sina_prefix 北交4", sina_prefix("430047") == "bj")

    import strategies as _S2
    seen = {}

    def fake_chain(name, links):
        fn = links[0][1]
        try:
            df = fn()
        except Exception as ex:
            seen["err"] = str(ex)
            raise
        seen["symbol"] = fn.__closure__[0].cell_contents
        return df

    orig = _S2.net_guard.try_chain
    _S2.net_guard.try_chain = fake_chain
    try:
        _S2.fetch_kline("920001")
        check("fetch_kline 北交所 bj前缀", seen.get("symbol") == "bj920001", str(seen))
    except Exception:
        check("fetch_kline 北交所 bj前缀", seen.get("symbol") == "bj920001", str(seen))
    _S2.net_guard.try_chain = orig
    return fails


if __name__ == "__main__":
    sys.exit(main())
