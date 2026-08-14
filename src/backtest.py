"""G4 历史回测：用历史新闻 CSV 回放 filter→decision→sim，验证策略。
严格无前视：T 日决策（当日收盘后）→ T+1 开盘价成交。
已接入方案 A/B/C：个股情绪覆盖（stock_sentiment_{date}.csv）、个股止损（T+1 开盘
判定，涨停不卖）、止损冷却（按交易日序列）、回调策略买入、超买降权。
支持 --grid 网格扫描参数敏感性（默认取 config 参数）。
用法：python src/backtest.py --start 2026-08-01 --end 2026-08-13
      python src/backtest.py --grid
"""
import sys
import re
import datetime as dt

import pandas as pd

from config import DATA_DIR, STOCKS, INIT_CASH, \
    STOP_LOSS_RATIO, STOP_COOLDOWN_DAYS, LIMIT_UP_PCT
from decision import STOCK_SENTI_MIN, STOCK_SENTI_CONF_N, OVERBOUGHT_LBC
import filter_news
import circuit_breaker as cb
import decision
import sim_account


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


def _load_backtest_pool(tdate: str) -> list:
    """回测池：优先当日 select_<tdate>.csv（与生产链路 select_stock 一致，T-1 涨停池盘前可用，
    严格无前视）；文件缺失/为空/读取失败 → 回退 config.STOCKS 基准池。
    返回项含 strategies（回调策略判定用），缺失为空串。"""
    p = DATA_DIR / f"select_{tdate}.csv"
    if p.exists():
        try:
            df = pd.read_csv(p, encoding="utf-8-sig", dtype={"symbol": str})
            if not df.empty:
                return [{"symbol": str(r["symbol"]), "name": str(r.get("name", "")),
                         "strategies": str(r.get("strategies", "") or "")}
                        for _, r in df.iterrows()]
            print(f"[warn] select_{tdate}.csv 为空，回退 STOCKS")
        except Exception as e:
            print(f"[warn] select_{tdate}.csv 读取失败: {e}，回退 STOCKS")
    return STOCKS


def _ensure_hist(sym: str, hist: dict, start: str, end: str) -> dict:
    """按需加载个股历史行情（select 池股票可能不在 STOCKS 中）。"""
    if sym not in hist:
        hist[sym] = load_hist_quotes(sym, start, end)
    return hist


def _split_strats(strategies: str) -> list:
    """select CSV 策略字段分隔兼容（,/、中文逗号）。"""
    return [s for s in re.split(r"[,/，]", strategies or "") if s]


def run_backtest(start, end, sl_ratio=None, sl_cool=None,
                 senti_min=None, senti_conf_n=None, grid=False):
    """回测主流程（方案 A/B/C 接入）。

    参数缺省取 config/decision 默认（--grid 时由网格注入）。
    返回 dict（grid 模式聚合用）：final/peak/max_drawdown/win_rate/trades。
    """
    sl_ratio = STOP_LOSS_RATIO if sl_ratio is None else sl_ratio
    sl_cool = STOP_COOLDOWN_DAYS if sl_cool is None else sl_cool
    senti_min = STOCK_SENTI_MIN if senti_min is None else senti_min
    senti_conf_n = STOCK_SENTI_CONF_N if senti_conf_n is None else senti_conf_n
    news_files = sorted(DATA_DIR.glob("news_*.csv"))
    news_dates = [f.stem.replace("news_", "") for f in news_files
                  if start <= f.stem.replace("news_", "") <= end]
    if not news_dates:
        print("[warn] 指定区间内无历史新闻文件")
        return {}
    hist = {s["symbol"]: load_hist_quotes(s["symbol"], start, end) for s in STOCKS}
    cash = INIT_CASH
    positions = {}
    trades = []
    peak = INIT_CASH
    max_drawdown = 0.0
    sl_day = {}  # symbol -> 止损日 news_dates 索引（冷却判定按交易日序列）
    sells_n = 0
    win_n = 0
    buys_n = 0
    sl_sells_n = 0

    for i, tdate in enumerate(news_dates):
        df = pd.read_csv(DATA_DIR / f"news_{tdate}.csv", encoding="utf-8-sig")
        df = filter_news.classify(df)
        summary = filter_news.summarize(df, tdate)
        score = summary["senti_score"]
        ss_map = decision.stock_senti_map(tdate)  # 个股情绪（方案B），缺失 fail-open
        pool = _load_backtest_pool(tdate)
        decisions = []
        for s in pool:
            sym = s["symbol"]
            _ensure_hist(sym, hist, start, end)
            q = hist[sym].get(tdate)
            change = q["pct"] if q else 0.0
            score_i = score
            w = 1.0
            ss = ss_map.get(sym)
            if ss is not None and int(ss.get("count", 0)) >= senti_min:
                score_i = float(ss["score"])
                w = min(1.0, int(ss["count"]) / senti_conf_n)
            strats = _split_strats(s.get("strategies", ""))
            is_cb = decision._is_callback(strats)
            if score_i > 0.3 and (change > 0 or is_cb):
                signal, predict = "buy", "up"
            elif score_i < -0.3:
                signal, predict = "sell", "down"
            else:
                signal, predict = "hold", "flat"
            if cb.in_cooldown():
                signal, predict = "hold", "flat"
            confidence = min(1.0, abs(score_i) + abs(change) / 10) * w
            if decision._overbought({}, s) and signal == "buy":
                confidence = max(0.0, confidence - 0.1)
            decisions.append({"date": tdate, "stock": sym, "signal": signal,
                              "predict": predict, "leverage": 1,
                              "confidence": round(confidence, 3),
                              "reason": f"回测情绪{score_i:.2f}"})
        next_date = news_dates[i + 1] if i + 1 < len(news_dates) else None
        if next_date:
            # 方案A：T+1 开盘先执行持仓止损（涨停不卖），写冷却
            st = {"positions": positions}
            quotes = {sym: {"price": hist[sym].get(next_date, {}).get("open", 0.0)}
                      for sym in positions}
            stop_orders = sim_account.stop_loss_signal(
                st, quotes, next_date, ratio=sl_ratio)
            for o in stop_orders:
                sym = o["stock"]
                nq = hist[sym].get(next_date)
                if not nq:
                    continue
                if nq["pct"] >= LIMIT_UP_PCT:
                    continue  # 涨停不卖（沿用生产规则）
                amount = positions[sym]["shares"] * nq["open"]
                fee = max(amount * 0.00025, 5.0) + amount * 0.0005
                pnl = amount - positions[sym]["shares"] * positions[sym]["cost"] - fee
                sells_n += 1
                win_n += 1 if pnl > 0 else 0
                sl_sells_n += 1
                cash += amount - fee
                trades.append({"date": next_date, "stock": sym, "action": "sell",
                               "price": nq["open"], "shares": positions[sym]["shares"],
                               "amount": round(amount, 2), "reason": "个股止损"})
                positions.pop(sym, None)
                sl_day[sym] = i + 1  # 止损成交日索引（next_date），冷却按交易日序列
            for d in decisions:
                sym = d["stock"]
                nq = hist[sym].get(next_date)
                if not nq:
                    continue
                if d["signal"] == "buy" and sym not in positions:
                    if nq["pct"] <= -9.9:
                        continue
                    if sym in sl_day and (i + 1 - sl_day[sym]) < sl_cool:
                        continue  # 止损冷却期内禁买（方案A）
                    budget = min(cash * 0.9, cash)
                    shares = (budget * 0.999) / nq["open"] // 100 * 100
                    if shares <= 0:
                        continue
                    amount = shares * nq["open"]
                    fee = max(amount * 0.00025, 5.0)
                    cash -= amount + fee
                    buys_n += 1
                    positions[sym] = {"shares": shares, "cost": amount / shares}
                    trades.append({"date": next_date, "stock": sym, "action": "buy",
                                   "price": nq["open"], "shares": shares,
                                   "amount": round(amount, 2), "reason": d["reason"]})
                elif d["signal"] == "sell" and sym in positions:
                    if nq["pct"] >= LIMIT_UP_PCT:
                        continue
                    amount = positions[sym]["shares"] * nq["open"]
                    fee = max(amount * 0.00025, 5.0) + amount * 0.0005
                    pnl = amount - positions[sym]["shares"] * positions[sym]["cost"] - fee
                    sells_n += 1
                    win_n += 1 if pnl > 0 else 0
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
    sells = [t for t in trades if t["action"] == "sell"]
    win_rate = win_n / sells_n if sells_n else 0.0
    label = f"（sl={sl_ratio}, cool={sl_cool}, min={senti_min}）" if grid else ""
    print(f"=== 回测结果 {start} → {end}（{len(news_dates)} 个新闻日）{label} ===")
    print(f"初始资金: {INIT_CASH:,.0f} → 期末: {final:,.0f} "
          f"({(final / INIT_CASH - 1) * 100:+.2f}%)")
    print(f"峰值资产: {peak:,.0f} | 最大回撤: {max_drawdown:.2%}")
    print(f"交易次数: {len(trades)}（买{sum(1 for t in trades if t['action']=='buy')}/"
          f"卖{sells_n}）| 胜率 {win_rate:.1%} | 止损卖出: "
          f"{sum(1 for t in sells if t['reason']=='个股止损')}")
    if not grid:
        rows_out = DATA_DIR / f"backtest_{start}_{end}.csv"
        pd.DataFrame(trades).to_csv(rows_out, index=False, encoding="utf-8-sig")
        print(f"明细 → {rows_out}")
    return {"final": final, "peak": peak, "max_drawdown": max_drawdown,
            "win_rate": round(win_rate, 3), "trades": len(trades),
            "buys": buys_n, "sl_sells": sl_sells_n}


def run_grid(start, end):
    """网格扫描：止损率 × 冷却日 × 个股情绪阈值 组合敏感性对照。"""
    import itertools
    combos = list(itertools.product([0.05, 0.08, 0.12], [3, 5, 7], [2, 3, 5]))
    print(f"=== 网格扫描 {len(combos)} 组（{start} → {end}）===")
    print(f"{'sl':>5} {'cool':>5} {'min':>5} | {'期末收益%':>9} {'最大回撤%':>9} "
          f"{'胜率%':>7} {'交易':>5}")
    for sl, cool, mn in combos:
        r = run_backtest(start, end, sl_ratio=sl, sl_cool=cool,
                         senti_min=mn, grid=True)
        if not r:
            return
        print(f"{sl:>5} {cool:>5} {mn:>5} | "
              f"{(r['final'] / INIT_CASH - 1) * 100:>+8.2f}% "
              f"{r['max_drawdown'] * 100:>8.2f}% {r['win_rate'] * 100:>6.1f}% "
              f"{r['trades']:>5}")


def main():
    args = sys.argv[1:]
    start = "2026-01-01"
    end = dt.date.today().isoformat()
    if "--start" in args:
        start = args[args.index("--start") + 1]
    if "--end" in args:
        end = args[args.index("--end") + 1]
    if "--grid" in args:
        run_grid(start, end)
        return
    run_backtest(start, end)


if __name__ == "__main__":
    main()