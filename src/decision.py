"""③ 决策：情绪分+个股当日涨跌幅 → 买卖信号+杠杆档位。
G8 辅助因子：技术指标/形态仅微调 confidence 与 reason，不改变买卖主规则。
G6 辅助因子：资金面（两融/北向）同样仅微调 confidence 与 reason，不改变主规则。
"""
import sys
import datetime as dt

import pandas as pd

from config import (DATA_DIR, SENTI_BUY_THRESHOLD, SENTI_SELL_THRESHOLD,
                    LEVERAGE_HIGH, LEVERAGE_MID, LEVERAGE_LOW, SENTI_SCORE_CUT)
import circuit_breaker as cb
import indicators
import kline_patterns
import fund_flow
import net_guard
import strategies
import market_env as me
import select_stock
import ml_advisor

STOCK_SENTI_MIN = 3        # 个股新闻 ≥3 条才用个股情绪覆盖市场情绪（方案B）
STOCK_SENTI_CONF_N = 10    # 个股情绪置信度 = min(1, 新闻条数/10)
CALLBACK_STRATS = {"回踩年线", "低波动启动", "无大跌回踩"}  # 低吸类策略（方案C）
OVERBOUGHT_LBC = 3         # 连板 ≥3 视为超买（方案C）
RSI_OVERBOUGHT = 80        # RSI >80 视为超买（方案C）


def _is_callback(strats: list) -> bool:
    """回调/低吸类策略命中 → 买入不要求当日上涨（企稳即可，方案C）。"""
    return any(s in CALLBACK_STRATS for s in strats)


def _overbought(m: dict, s: dict) -> bool:
    """超买判定：RSI>80 或 连板≥3（方案C）。技术因子缺失时仅按连板判定。"""
    rsi = (m.get("rsi") or {}).get("rsi")
    if rsi is not None and float(rsi) > RSI_OVERBOUGHT:
        return True
    return int(s.get("lbc", 0) or 0) >= OVERBOUGHT_LBC


def stock_senti_map(date_str: str) -> dict:
    """读取当日个股情绪（filter_news 生成 stock_sentiment_{date}.csv）。失败返回 {}。"""
    f = DATA_DIR / f"stock_sentiment_{date_str}.csv"
    if not f.exists():
        return {}
    try:
        df = pd.read_csv(f, encoding="utf-8-sig", dtype={"stock": str})
        return {str(r["stock"]): r for _, r in df.iterrows()}
    except Exception as e:
        print(f"[warn] 个股情绪读取失败: {e}")
        return {}


def fetch_spot(pool: list) -> dict:
    """全A实时快照，取观察池股票涨跌幅。东财直连优先，失败降级到新浪日K。"""
    symbols = {s["symbol"] for s in pool}
    try:
        import akshare as ak
        df = net_guard.try_chain("东财快照", [("em", lambda: ak.stock_zh_a_spot_em())])
        df = df[df["代码"].isin(symbols)]
        return {r["代码"]: float(r["涨跌幅"]) for _, r in df.iterrows()}
    except Exception as e:
        print(f"[warn] 东财行情失败: {e}，降级新浪日K")
        return fetch_spot_sina(pool)


def fetch_spot_sina(pool: list) -> dict:
    """新浪日K降级：涨跌幅=(最新close-昨日close)/昨日close*100。"""
    import akshare as ak
    result = {}
    for s in pool:
        sym = s["symbol"]
        prefix = "sh" if sym.startswith("6") else "sz"
        try:
            df = ak.stock_zh_a_daily(symbol=prefix + sym)
            if df is not None and not df.empty and len(df) >= 2:
                c = float(df.iloc[-1]["close"]); p = float(df.iloc[-2]["close"])
                result[sym] = round((c - p) / p * 100, 2)
        except Exception as e:
            print(f"[warn] {sym} 新浪行情失败: {e}")
    return result


def tech_factor(sym: str, date_str: str = None) -> dict:
    """G8 辅助因子：返回 (技术摘要, 形态列表)。失败返回空值，不阻断决策。
    date_str 按该日收盘数据计算（回测/补跑不含未来数据）。"""
    try:
        df = indicators.fetch_daily(sym, asof=date_str)
        m = indicators.analyze(df)
        patterns = kline_patterns.detect(df)
        return m, patterns
    except Exception as e:
        print(f"[warn] {sym} 技术因子失败: {e}")
        return {"ok": False, "reason": "技术因子不可用"}, []


def fund_factor_extra(today: str) -> dict:
    """G6 资金面辅助因子（大盘级，每日一次）：微调 confidence（±0.05）并生成摘要。"""
    try:
        return fund_flow.fund_factor(today)
    except Exception as e:
        print(f"[warn] 资金面因子失败: {e}")
        return {"conf": 0.0, "label": "", "unavailable": []}


def strategy_factor(sym: str, date_str: str = None) -> list:
    """InStock 经典策略因子：命中策略中文名列表。失败返回 []，不阻断决策。
    date_str 按该日收盘数据判定（回测/补跑不含未来数据）。"""
    try:
        return strategies.detect(sym, date_str)
    except Exception as e:
        print(f"[warn] {sym} 策略因子失败: {e}")
        return []


def decide(score: float, spot: dict, pool: list, date_str: str = None) -> list:
    """决策。date_str 为决策日（--date 补跑时区别于运行日，避免资金面/市场
    环境/ML/个股情绪误读"今天"）。缺省取运行日。"""
    date_str = date_str or dt.date.today().isoformat()
    rows = []
    ff = fund_factor_extra(date_str)  # G6 资金面
    env = me.market_env(date_str)  # 大盘环境，None=数据不可用不压制
    ml = ml_advisor.advice(date_str)  # ML 风控，数据不足 fail-open
    ss_map = stock_senti_map(date_str)  # 个股情绪（方案B）
    for s in pool:
        sym = s["symbol"]
        if sym not in spot:
            rows.append({"date": date_str, "stock": sym,
                         "signal": "hold", "leverage": LEVERAGE_LOW,
                         "predict": "none", "confidence": 0.0,
                         "reason": "行情unavailable，数据缺失宁缺毋假，跳过决策"})
            continue
        change = spot.get(sym, 0.0)
        m, patterns = tech_factor(sym, date_str)
        strats = strategy_factor(sym, date_str)
        tech_note = indicators.describe(m) if m.get("ok") else (m.get("reason") or "技术面跳过")
        if patterns:
            tech_note += " | 形态: " + "/".join(patterns)
        if strats:
            tech_note += " | 策略: " + "/".join(strats)
        score_i = score  # 个股情绪有效时覆盖市场情绪（仅信号判定与置信度）
        w = 1.0
        senti_note = ""
        ss = ss_map.get(sym)
        if ss is not None and int(ss.get("count", 0)) >= STOCK_SENTI_MIN:
            score_i = float(ss["score"])
            w = min(1.0, int(ss["count"]) / STOCK_SENTI_CONF_N)
            senti_note = f" | 个股情绪: {score_i:+.2f}({int(ss['count'])}条)"
        if score_i > SENTI_BUY_THRESHOLD and (change > 0 or _is_callback(strats)):
            signal = "buy"
            predict = "up"
            confidence = min(1.0, abs(score_i) + abs(change) / 10) * w
            if _is_callback(strats) and change <= 0:
                reason = f"情绪{score_i:.2f}>0.3 且 {s['name']}回调企稳（{','.join(strats)}）"
            else:
                reason = f"情绪{score_i:.2f}>0.3 且 {s['name']}涨{change:.2f}%"
            if m.get("ok") and m.get("ma_bullish"):
                confidence = min(1.0, confidence + 0.1)  # 均线多头共振小幅加成
                reason += "（均线多头共振）"
            if strats:
                bonus = min(0.1, 0.02 * len(strats))  # 策略命中每条 +0.02，封顶 +0.1
                confidence = min(1.0, confidence + bonus)
                reason += "（策略命中）"
            signal, confidence, score, soft_note = me.guard(env, signal, confidence, score)
            if soft_note:
                predict = "flat"
                reason += f"（{soft_note}）"
            if _overbought(m, s):
                confidence = max(0.0, confidence - 0.1)
                reason += "（超买降权）"
        elif score_i < SENTI_SELL_THRESHOLD:
            signal = "sell"
            predict = "down"
            confidence = min(1.0, abs(score_i)) * w
            reason = f"情绪{score_i:.2f}<{-0.3}"
        else:
            signal = "hold"
            predict = "flat"
            confidence = abs(score_i) * w
            reason = f"情绪{score_i:.2f} 观望"
        if score >= SENTI_SCORE_CUT:
            leverage = LEVERAGE_HIGH
        elif score >= SENTI_BUY_THRESHOLD:
            leverage = LEVERAGE_MID
        else:
            leverage = LEVERAGE_LOW
        leverage = min(leverage, cb.leverage_cap())
        if cb.in_cooldown():
            signal = "hold"
            predict = "flat"
            reason = f"熔断冷却中({cb.status_text()})，暂停交易"
        if ff.get("conf"):
            confidence = min(1.0, max(0.0, confidence + ff["conf"]))
        if ml.get("intervene"):
            confidence = min(1.0, max(0.0, confidence - ml["penalty"]))
            reason += f" | {ml['reason']}"
        reason += senti_note
        reason += f" | {tech_note}"
        if ff.get("label"):
            reason += f" | 资金面: {ff['label']}"
        if env:
            reason += f" | 市场: {env['note']}"
        rows.append({"date": date_str, "stock": sym,
                     "signal": signal, "leverage": leverage,
                     "predict": predict, "confidence": round(confidence, 4),
                     "reason": reason})
    return rows


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    senti = pd.read_csv(DATA_DIR / "daily_sentiment.csv", encoding="utf-8-sig")
    last = senti.iloc[-1]
    pool = select_stock.load_pool(date_str)
    rows = decide(float(last["senti_score"]), fetch_spot(pool), pool, date_str)
    out = DATA_DIR / f"decision_{date_str}.csv"
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[ok] 决策 {len(rows)} 条 → {out}")
    for r in rows:
        print(f"  {r['stock']} {r['signal']:5s} 杠杆{r['leverage']}倍 | {r['reason']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    main(date_str)