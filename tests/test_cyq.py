"""筹码分布测试（CYQ，InStock 融入）：构造确定性序列验证获利盘/边界。"""
import sys
import datetime as dt
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import cyq


def _kline(closes, vol=1000.0):
    rows = []
    d0 = dt.date(2026, 1, 1)
    for i, c in enumerate(closes):
        rows.append({"date": (d0 + dt.timedelta(days=i)).isoformat(),
                     "open": c, "high": c * 1.02, "low": c * 0.98,
                     "close": c, "volume": vol})
    return pd.DataFrame(rows)


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # --- 单调上涨：低位筹码积累，获利盘高 ---
    up = [10.0 + 0.1 * i for i in range(60)]
    r = cyq.cyq(_kline(up))
    check("上涨获利盘>0.9", r is not None and r["winner"] > 0.9,
          f"winner={r['winner']:.2%}" if r else "None")

    # --- 高位套牢：冲高回落后现价低位，获利盘低 ---
    trap = [10.0 + 0.3 * i for i in range(60)] + [40.0 - 0.5 * i for i in range(60)]
    r = cyq.cyq(_kline(trap))
    check("套牢获利盘<0.5", r is not None and r["winner"] < 0.5,
          f"winner={r['winner']:.2%}" if r else "None")

    # --- 边界：空数据 / 数据不足 / 缺列 ---
    check("空表=None", cyq.cyq(pd.DataFrame()) is None)
    check("不足30行=None", cyq.cyq(_kline(up[:20])) is None)
    bad = _kline(up).drop(columns=["volume"])
    check("缺volume列=None", cyq.cyq(bad) is None)

    # --- 一字板（high==low）不崩溃：与正常K线混用 ---
    rows = _kline(up)
    r = cyq.cyq(pd.concat([rows, pd.DataFrame([{"date": "2026-04-01", "open": 16.0,
                                                "high": 16.0, "low": 16.0,
                                                "close": 16.0, "volume": 800.0}])],
                          ignore_index=True))
    check("一字板不崩溃", r is not None and 0 <= r["winner"] <= 1)

    # --- 摘要文本 ---
    s = cyq.summarize(r)
    check("摘要含获利盘", "获利盘" in s and "集中度" in s, s)
    check("摘要None", cyq.summarize(None) == "筹码分布: 数据不足/不可用")

    print("\ncyq tests done.")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)