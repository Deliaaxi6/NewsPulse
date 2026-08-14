"""大盘环境护栏（参考 daily_stock_analysis 的 daily_market_context_guardrail）：
三大指数涨跌幅 + 涨跌家数 → 弱势判定；弱势时对个股信号统一软化
（buy→hold、情绪分/置信度封顶），reason 追加说明。全部数据失败 → None（宁缺毋假），不阻断决策。

数据源：新浪指数日K（东财指数快照在本机被代理拦截，直接降级新浪）；
涨跌家数：乐咕乐股 stock_market_activity_legu（长表 item/value，失败返回 None 只按指数判定）。
"""
import datetime as dt

import pandas as pd

import net_guard

WEAK_INDEX_DROP = -1.5    # 任一主要指数当日跌幅 ≤ 该值 → 弱势
WEAK_DOWN_UP_RATIO = 2.0  # 跌家数 / 涨家数 ≥ 该值 → 弱势
SCORE_CAP = 0.5           # 弱势时情绪分封顶
CONF_CAP = 0.5            # 弱势时置信度封顶

INDEX_LIST = [("上证指数", "sh000001"), ("深证成指", "sz399001"), ("创业板指", "sz399006")]
ACTIVITY_ITEMS = {"上涨": "up", "下跌": "down", "涨停": "limit_up", "跌停": "limit_down"}


def fetch_index_changes():
    """三大指数当日涨跌幅（新浪日K降级链）。全部失败返回 None。"""
    import akshare as ak

    result = {}
    for name, symbol in INDEX_LIST:
        try:
            df = net_guard.try_chain(
                f"新浪指数{symbol}",
                [("sina", lambda: ak.stock_zh_index_daily(symbol=symbol))])
            if df is None or df.empty or len(df) < 2:
                continue
            c = float(df.iloc[-1]["close"])
            p = float(df.iloc[-2]["close"])
            if p <= 0:
                continue
            result[name] = round((c - p) / p * 100, 2)
        except Exception as e:
            print(f"[warn] 指数 {name} 行情失败: {e}")
    return result or None


def fetch_market_activity():
    """涨跌家数（乐咕乐股长表）。失败返回 None，弱市判定退化为纯指数。"""
    import akshare as ak

    try:
        df = net_guard.try_chain("涨跌家数", [("legu", lambda: ak.stock_market_activity_legu())])
        if df is None or df.empty or "item" not in df.columns:
            return None
        kv = dict(zip(df["item"].astype(str).str.strip(), df["value"]))
        out = {}
        for item_name, key in ACTIVITY_ITEMS.items():
            for raw, val in kv.items():
                if item_name in raw:
                    try:
                        out[key] = float(val)
                    except (TypeError, ValueError):
                        pass
                    break
        return out or None
    except Exception as e:
        print(f"[warn] 涨跌家数失败: {e}")
        return None


def is_weak(changes, activity):
    """弱势判定：任一主要指数跌幅 ≤ -1.5% 或 跌家数/涨家数 ≥ 2。"""
    if changes and any(v <= WEAK_INDEX_DROP for v in changes.values()):
        return True
    if activity:
        up, down = activity.get("up", 0), activity.get("down", 0)
        if up > 0 and down / up >= WEAK_DOWN_UP_RATIO:
            return True
    return False


def market_env(date_str=None):
    """返回 {changes, activity, weak, note}；全部数据不可用返回 None（宁缺毋假）。"""
    date_str = date_str or dt.date.today().isoformat()
    changes = fetch_index_changes()
    activity = fetch_market_activity()
    if not changes and not activity:
        return None
    weak = is_weak(changes, activity)
    parts = []
    if changes:
        parts.append("指数: " + " ".join(f"{k}{v:+.2f}%" for k, v in changes.items()))
    if activity:
        parts.append("家数: 涨%s/跌%s" % (activity.get("up", "?"), activity.get("down", "?")))
    note = f"市场{date_str} " + "; ".join(parts) + ("（弱势，信号软化处理）" if weak else "（正常）")
    return {"changes": changes, "activity": activity, "weak": weak, "note": note}


def guard(env, signal, confidence, score):
    """弱势软化：buy→hold、情绪分/置信度封顶。返回 (signal, confidence, score, note)。
    env 为 None 或非弱势 → 原样返回，note 为 None。"""
    if not env or not env.get("weak"):
        return signal, confidence, score, None
    if signal == "buy":
        signal = "hold"
    return signal, min(confidence, CONF_CAP), min(score, SCORE_CAP), "市场弱势已软化"


def main(date_str=None):
    env = market_env(date_str)
    if not env:
        print("[warn] 大盘环境数据不可用（宁缺毋假）")
        return
    print(f"[ok] {env['note']}")
    if env["weak"]:
        print(f"[ok] 判定弱势 → 买入信号将软化为观望，情绪分封顶 {SCORE_CAP}")


if __name__ == "__main__":
    main(__import__("sys").argv[1] if len(__import__("sys").argv) > 1 else None)
