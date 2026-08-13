"""③ 决策：情绪分+个股当日涨跌幅 → 买卖信号+杠杆档位。"""
import sys
import datetime as dt

import pandas as pd

from config import (DATA_DIR, STOCKS, SENTI_BUY_THRESHOLD, SENTI_SELL_THRESHOLD,
                    LEVERAGE_HIGH, LEVERAGE_MID, LEVERAGE_LOW, SENTI_SCORE_CUT)
import circuit_breaker as cb


def fetch_spot():
    """全A实时快照，取4只股票涨跌幅。失败降级到新浪日K。"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        df = df[df["代码"].isin([s["symbol"] for s in STOCKS])]
        return {r["代码"]: float(r["涨跌幅"]) for _, r in df.iterrows()}
    except Exception as e:
        print(f"[warn] 东财行情失败: {e}，降级新浪日K")
        return fetch_spot_sina()


def fetch_spot_sina():
    """新浪日K降级：涨跌幅=(最新close-昨日close)/昨日close*100。"""
    import akshare as ak
    result = {}
    for s in STOCKS:
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


def decide(score: float, spot: dict) -> list:
    rows = []
    for s in STOCKS:
        sym = s["symbol"]
        if sym not in spot:
            rows.append({"date": dt.date.today().isoformat(), "stock": sym,
                         "signal": "hold", "leverage": LEVERAGE_LOW,
                         "predict": "none", "confidence": 0.0,
                         "reason": "行情unavailable，数据缺失宁缺毋假，跳过决策"})
            continue
        change = spot.get(sym, 0.0)
        if score > SENTI_BUY_THRESHOLD and change > 0:
            signal = "buy"
            predict = "up"
            confidence = min(1.0, abs(score) + abs(change) / 10)
            reason = f"情绪{score:.2f}>0.3 且 {s['name']}涨{change:.2f}%"
        elif score < SENTI_SELL_THRESHOLD:
            signal = "sell"
            predict = "down"
            confidence = min(1.0, abs(score))
            reason = f"情绪{score:.2f}<{-0.3}"
        else:
            signal = "hold"
            predict = "flat"
            confidence = abs(score)
            reason = f"情绪{score:.2f} 观望"
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
        rows.append({"date": dt.date.today().isoformat(), "stock": sym,
                     "signal": signal, "leverage": leverage,
                     "predict": predict, "confidence": round(confidence, 4),
                     "reason": reason})
    return rows


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    senti = pd.read_csv(DATA_DIR / "daily_sentiment.csv", encoding="utf-8-sig")
    last = senti.iloc[-1]
    rows = decide(float(last["senti_score"]), fetch_spot())
    out = DATA_DIR / f"decision_{date_str}.csv"
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[ok] 决策 {len(rows)} 条 → {out}")
    for r in rows:
        print(f"  {r['stock']} {r['signal']:5s} 杠杆{r['leverage']}倍 | {r['reason']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)