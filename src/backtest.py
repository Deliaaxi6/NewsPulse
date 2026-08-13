"""G4 历史回测：用历史新闻 CSV 回放 filter→decision→sim，验证策略。
严格无前视：T 日决策（当日收盘后）→ T+1 开盘价成交。
用法：python src/backtest.py --start 2026-08-01 --end 2026-08-13
"""
import sys
import datetime as dt

import pandas as pd

from config import DATA_DIR, STOCKS, INIT_CASH
import filter_news
import circuit_breaker as cb


def load_hist_quotes(symbol, start, end):
    """历史日K（新浪）：返回 {date: {open, close, pct}}。"""
    import akshare as ak
    prefix = "sh" if symbol.startswith("6") else "sz"
    df = ak.stock_zh_a_daily(symbol=prefix + symbol,
                             start_date=start.replace("-", ""),
                             end_date=end.replace("-", ""))
    if df is None or df.empty:
        return {}
    rows = {}
    for _, r in df.iterrows():
        d = str(r["date"])[:10]
        o = float(r["open"])
        rows[d] = {"open": o, "close": float(r["close"])}
    dates = sorted(rows)
    for i, d in enumerate(dates):
        if i > 0:
            prev_close = rows[dates[i - 1]]["close"]
            rows[d]["pct"] = round((rows[d]["close"] - prev_close) / prev_close * 100, 2)
        else:
            rows[d]["pct"] = 0.0
    return rows


def _latest_close(hist: dict, upto: str) -> float:
    """前向填充：返回不晚于 upto 的最新收盘价，缺失返回 0（不该发生）。"""
    for d in sorted(hist):
        if d > upto:
            break
        last = hist[d]["close"]
    return last


def run_backtest(start, end):
    news_files = sorted(DATA_DIR.glob("news_*.csv"))
    news_dates = [f.stem.replace("news_", "") for f in news_files
                  if start <= f.stem.replace("news_", "") <= end]
    if not news_dates:
        print("[warn] 指定区间内无历史新闻文件")
        return
    hist = {s["symbol"]: load_hist_quotes(s["symbol"], start, end) for s in STOCKS}
    cash = INIT_CASH
    positions = {}
    trades = []
    peak = INIT_CASH
    max_drawdown = 0.0
    predict_records = []

    for i, tdate in enumerate(news_dates):
        df = pd.read_csv(DATA_DIR / f"news_{tdate}.csv", encoding="utf-8-sig")
        df = filter_news.classify(df)
        summary = filter_news.summarize(df, tdate)
        score = summary["senti_score"]
        decisions = []
        for s in STOCKS:
            sym = s["symbol"]
            q = hist[sym].get(tdate)
            change = q["pct"] if q else 0.0
            if score > 0.3 and change > 0:
                signal, predict = "buy", "up"
            elif score < -0.3:
                signal, predict = "sell", "down"
            else:
                signal, predict = "hold", "flat"
            if cb.in_cooldown():
                signal, predict = "hold", "flat"
            decisions.append({"date": tdate, "stock": sym, "signal": signal,
                              "predict": predict, "leverage": 1,
                              "confidence": abs(score), "reason": f"回测情绪{score:.2f}"})
        next_date = news_dates[i + 1] if i + 1 < len(news_dates) else None
        if next_date:
            for d in decisions:
                sym = d["stock"]
                nq = hist[sym].get(next_date)
                if not nq:
                    continue
                if d["signal"] == "buy" and sym not in positions:
                    if nq["pct"] <= -9.9:
                        continue
                    budget = min(cash * 0.9, cash)
                    shares = (budget * 0.999) / nq["open"] // 100 * 100
                    if shares <= 0:
                        continue
                    amount = shares * nq["open"]
                    fee = max(amount * 0.00025, 5.0)
                    cash -= amount + fee
                    positions[sym] = {"shares": shares, "cost": amount / shares}
                    trades.append({"date": next_date, "stock": sym, "action": "buy",
                                   "price": nq["open"], "shares": shares,
                                   "amount": round(amount, 2), "reason": d["reason"]})
                elif d["signal"] == "sell" and sym in positions:
                    if nq["pct"] >= 9.9:
                        continue
                    amount = positions[sym]["shares"] * nq["open"]
                    fee = max(amount * 0.00025, 5.0) + amount * 0.0005
                    cash += amount - fee
                    trades.append({"date": next_date, "stock": sym, "action": "sell",
                                   "price": nq["open"], "shares": positions[sym]["shares"],
                                   "amount": round(amount, 2), "reason": d["reason"]})
                    positions.pop(sym, None)
            mv = sum(positions[s]["shares"] * hist[s].get(next_date, {}).get("close", 0)
                     for s in positions)
            total = cash + mv
            peak = max(peak, total)
            max_drawdown = max(max_drawdown, (peak - total) / peak)
        cb.record_sentiment(score)

    mv = sum(positions[s]["shares"] * _latest_close(hist[s], news_dates[-1])
             for s in positions)
    final = cash + mv
    win_trades = [t for t in trades if t["action"] == "sell"]
    print(f"=== 回测结果 {start} → {end}（{len(news_dates)} 个新闻日）===")
    print(f"初始资金: {INIT_CASH:,.0f} → 期末: {final:,.0f} "
          f"({(final / INIT_CASH - 1) * 100:+.2f}%)")
    print(f"峰值资产: {peak:,.0f} | 最大回撤: {max_drawdown:.2%}")
    print(f"交易次数: {len(trades)}（买{sum(1 for t in trades if t['action']=='buy')}/"
          f"卖{len(win_trades)}）")
    rows_out = DATA_DIR / f"backtest_{start}_{end}.csv"
    pd.DataFrame(trades).to_csv(rows_out, index=False, encoding="utf-8-sig")
    print(f"明细 → {rows_out}")


def main():
    args = sys.argv[1:]
    start = "2026-01-01"
    end = dt.date.today().isoformat()
    if "--start" in args:
        start = args[args.index("--start") + 1]
    if "--end" in args:
        end = args[args.index("--end") + 1]
    run_backtest(start, end)


if __name__ == "__main__":
    main()