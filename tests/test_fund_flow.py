"""资金面因子测试（G6）：注入构造数据验证趋势/信号/边界，不依赖网络。"""
import sys
import datetime as dt
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import fund_flow


def _margin(vals, start="2026-07-01"):
    d0 = dt.date.fromisoformat(start)
    return pd.DataFrame({
        "trade_date": [d0 + dt.timedelta(days=i) for i in range(len(vals))],
        "rzrqye": vals,
    })


def _north(net, date_seq):
    return pd.DataFrame({"trade_date": date_seq, "net_tgt": net})


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # --- 趋势：递增 → 扩张；递减 → 回落；平稳 → 持平 ---
    up = _margin([100.0 + i for i in range(40)])
    mt = fund_flow.margin_trend(up)
    check("两融递增=扩张", mt["dir"] == "expand", mt["label"])

    down = _margin([200.0 - i for i in range(40)])
    mt = fund_flow.margin_trend(down)
    check("两融递减=回落", mt["dir"] == "shrink", mt["label"])

    flat = _margin([100.0] * 40)
    mt = fund_flow.margin_trend(flat)
    check("两融平稳=持平", mt["dir"] == "flat", mt["label"])

    # --- 边界：数据不足 ---
    check("两融数据不足=unavailable", fund_flow.margin_trend(_margin([1.0, 2.0]))["dir"] == "unavailable")
    check("两融None=unavailable", fund_flow.margin_trend(None)["dir"] == "unavailable")

    # --- 边界：基期异常（全0）--- 
    zero = _margin([0.0] * 20)
    check("两融基期0=unavailable", fund_flow.margin_trend(zero)["dir"] == "unavailable")

    # --- 北向信号 ---
    seq = [dt.date(2026, 7, i) for i in range(1, 6)]
    ns = fund_flow.north_signal(_north([10.0, -5.0, 20.0, 8.0, 3.0], seq))
    check("北向净流入", ns["dir"] == "inflow", ns["label"])
    ns = fund_flow.north_signal(_north([-10.0, -5.0], seq[-2:]))
    check("北向净流出", ns["dir"] == "outflow", ns["label"])
    check("北向None=unavailable", fund_flow.north_signal(None)["dir"] == "unavailable")

    # --- 组合因子 ---
    ff = fund_flow.fund_factor("2026-08-10", margin_df=up)
    check("扩张+北向缺失: conf=+0.05", ff["conf"] == 0.05, str(ff))
    check("unavailable标注北向", any("北向" in u for u in ff["unavailable"]))

    ff = fund_flow.fund_factor("2026-08-10", margin_df=down)
    check("回落: conf=-0.05", ff["conf"] == -0.05, str(ff))

    ff = fund_flow.fund_factor("2026-08-10", margin_df=down, north_df=_north([10.0], seq[:1]))
    check("回落+流入: conf≈0", ff["conf"] == 0.0, str(ff))

    ff = fund_flow.fund_factor("2026-08-10", margin_df=pd.DataFrame(), north_df=pd.DataFrame())
    check("全缺失: conf=0 不抛异常", ff["conf"] == 0.0 and len(ff["unavailable"]) >= 1, str(ff))

    # --- 交易日历（注入假日历，不依赖网络）---
    fake_cal = pd.DataFrame({"trade_date": [dt.date(2026, 8, 10), dt.date(2026, 8, 11)],
                             "is_open": [True, False]})
    check("日历: 8-10开市", fund_flow.is_trading_day("2026-08-10", fake_cal) is True)
    check("日历: 8-11休市", fund_flow.is_trading_day("2026-08-11", fake_cal) is False)
    check("日历: 不在表中=None", fund_flow.is_trading_day("2025-01-01", fake_cal) is None)
    check("日历: 空日历=None", fund_flow.is_trading_day("2026-08-10", pd.DataFrame()) is None)

    cal3 = pd.DataFrame({"trade_date": [dt.date(2026, 8, 10), dt.date(2026, 8, 11),
                                        dt.date(2026, 8, 12), dt.date(2026, 8, 14)],
                         "is_open": [True, False, True, True]})
    check("区间: 含两端开市日=2", fund_flow.trading_days_between("2026-08-10", "2026-08-12", cal3) == 2)
    check("区间: 跨休市日=3", fund_flow.trading_days_between("2026-08-10", "2026-08-14", cal3) == 3)
    check("区间: 倒序归一=2", fund_flow.trading_days_between("2026-08-14", "2026-08-11", cal3) == 2)
    check("区间: 空日历=None", fund_flow.trading_days_between("2026-08-10", "2026-08-14", pd.DataFrame()) is None)

    print("\nfund_flow tests done.")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)