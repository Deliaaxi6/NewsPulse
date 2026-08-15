"""④ 模拟撮合：T+1、佣金/印花税、单票≤30% 总仓≤90%，涨停不卖/跌停不买。

含预测校验：对前一日 decision_*.csv 的预测做次日回馈（predict vs actual）。
"""
import sys
import datetime as dt

import pandas as pd

from config import (DATA_DIR, INIT_CASH, MAX_POSITION_RATIO, MAX_TOTAL_RATIO,
                    COMMISSION_RATE, STAMP_TAX, MIN_COMMISSION, LIMIT_UP_PCT,
                    LIMIT_DOWN_PCT, ONE_WORD_TOL, STOP_LOSS_RATIO,
                    STOP_COOLDOWN_DAYS)
import circuit_breaker as cb
import net_guard
import select_stock
import fund_flow
import alert

FLAT_BAND = 1.0  # |涨跌幅| < FLAT_BAND% 视为 "flat"


def is_one_word_board(q: dict) -> bool:
    """一字板：open==high==low，且涨跌幅达板级（无法成交）。
    涨跌幅不可用（pct=None，腾讯分时降级）时不判定一字板，宁缺毋假。"""
    o, h, l = q.get("open"), q.get("high"), q.get("low")
    pct = q.get("pct")
    if None in (o, h, l) or pct is None:
        return False
    return abs(h - o) <= ONE_WORD_TOL and abs(l - o) <= ONE_WORD_TOL and abs(pct) >= 9.0


def log_blocked(today, stock, reason):
    bfile = DATA_DIR / "blocked_log.csv"
    pd.DataFrame([{"date": today, "stock": stock, "reason": reason}]).to_csv(
        bfile, index=False, encoding="utf-8-sig",
        mode="a", header=not bfile.exists())
    print(f"[block] {today} {stock} {reason}")


def peak_value_ever() -> float:
    """历史峰值总资产（从 portfolio.csv 取最大 total_value，初始为 INIT_CASH）。"""
    p = DATA_DIR / "portfolio.csv"
    if p.exists():
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
            if not df.empty:
                return max(float(df["total_value"].max()), INIT_CASH)
        except Exception:
            pass
    return INIT_CASH


def latest_quote(pool: list):
    """行情降级链：东财快照 → 新浪日K → 腾讯分时（adata，仅价格）。东财直连优先。"""
    try:
        import akshare as ak
        df = net_guard.try_chain("东财快照", [("em", lambda: ak.stock_zh_a_spot_em())])
        df = df[df["代码"].isin([s["symbol"] for s in pool])]
        return {r["代码"]: {"price": float(r["最新价"]), "pct": float(r["涨跌幅"])}
                for _, r in df.iterrows()}
    except Exception as e:
        print(f"[warn] 东财行情失败: {e}，降级新浪日K")
    sina = latest_quote_sina(pool)
    if sina:
        return sina
    print("[warn] 新浪行情不可用，降级腾讯分时（仅价格，涨跌幅未知）")
    return latest_quote_qq(pool)


def latest_quote_qq(pool: list):
    """腾讯分时降级：最新成交价；无昨收无法计算涨跌幅，pct=None（宁缺毋假）。"""
    import adata
    result = {}
    qq = adata.stock.market.qq_market
    for s in pool:
        sym = s["symbol"]
        try:
            df = qq.get_market_bar(stock_code=sym)
            if df is not None and len(df):
                result[sym] = {"price": float(df.iloc[-1]["price"]),
                               "pct": None, "open": None, "high": None, "low": None}
        except Exception as e:
            print(f"[warn] {sym} 腾讯分时失败: {e}")
    return result


def latest_quote_sina(pool: list):
    """新浪日K降级：price=最新close，pct=(最新close-昨日close)/昨日close*100。"""
    import akshare as ak
    result = {}
    for s in pool:
        sym = s["symbol"]
        prefix = "sh" if sym.startswith("6") else "sz"
        try:
            df = ak.stock_zh_a_daily(symbol=prefix + sym)
            if df is not None and not df.empty and len(df) >= 2:
                last, prev = df.iloc[-1], df.iloc[-2]
                c = float(last["close"]); p = float(prev["close"])
                result[sym] = {"price": c, "pct": round((c - p) / p * 100, 2),
                               "open": float(last["open"]), "high": float(last["high"]),
                               "low": float(last["low"]), "close": float(last["close"])}
        except Exception as e:
            print(f"[warn] {sym} 新浪行情失败: {e}")
    return result


def load_portfolio():
    p = DATA_DIR / "portfolio.csv"
    if p.exists():
        pf = pd.read_csv(p, encoding="utf-8-sig", dtype={"stock": str}).to_dict("records")
        if pf:
            last = pf[-1]
            if last["date"] != dt.date.today().isoformat():
                return {"cash": float(last["cash"]), "positions": {r["stock"]: {"shares": float(r["shares"]), "cost": float(r["cost"]), "leverage": float(r.get("leverage", 1))}
                        for r in pf if r["date"] == last["date"]}}
    return {"cash": INIT_CASH, "positions": {}}


def positions_rows(state, today, quotes, pool):
    rows = []
    for s in pool:
        sym = s["symbol"]
        pos = state["positions"].get(sym)
        q = quotes.get(sym, {})
        price = q.get("price", 0.0)
        shares = pos["shares"] if pos else 0.0
        mv = shares * price
        rows.append({"date": today, "stock": sym, "shares": shares,
                     "cost": pos["cost"] if pos else 0.0, "market_value": round(mv, 2),
                     "cash": round(state["cash"], 2), "leverage": pos["leverage"] if pos else 1.0,
                     "total_value": round(state["cash"] + mv, 2)})
    return rows


def _stop_cooled(sym: str, today: str) -> bool:
    """该股最近止损日距今 < STOP_COOLDOWN_DAYS 交易日 → 冷却中禁止买入。
    交易日历不可用时降级自然日（fail-open，与熔断冷却同模式）。"""
    f = DATA_DIR / "stop_loss_log.csv"
    if not f.exists():
        return False
    try:
        df = pd.read_csv(f, encoding="utf-8-sig", dtype={"stock": str})
        dates = df[df["stock"].astype(str) == sym]["date"]
    except Exception:
        return False
    if dates.empty:
        return False
    last = str(dates.iloc[-1])
    days = fund_flow.trading_days_between(last, today)
    if days is None:
        days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(last)).days
    return days < STOP_COOLDOWN_DAYS


def stop_loss_signal(state: dict, quotes: dict, today: str,
                     ratio: float = None) -> list:
    """持仓成本回撤 ≥STOP_LOSS_RATIO → 生成止损卖出决策（与普通 sell 同路径成交，
    涨停不卖/一字板保护由 run_orders 统一处理）。成本缺失/无行情跳过，宁缺毋假。
    ratio 缺省取 config.STOP_LOSS_RATIO（回测网格扫描可注入不同值）。"""
    ratio = STOP_LOSS_RATIO if ratio is None else ratio
    rows = []
    for sym, pos in state["positions"].items():
        if pos.get("shares", 0) <= 0 or not pos.get("cost"):
            continue
        q = quotes.get(sym)
        if not q or not q.get("price"):
            continue
        cost = float(pos["cost"])
        price = float(q["price"])
        if cost <= 0:
            continue
        drawdown = (price - cost) / cost
        if drawdown <= -ratio:
            rows.append({"stock": sym, "signal": "sell",
                         "leverage": pos.get("leverage", 1),
                         "reason": f"个股止损（成本{cost:.2f}→现价{price:.2f}，"
                                   f"回撤{drawdown:.1%}）"})
    return rows


def run_orders(state, decisions, quotes, today, logs, pool):
    total_value = state["cash"] + sum(
        state["positions"].get(s["symbol"], {}).get("shares", 0) * quotes.get(s["symbol"], {}).get("price", 0)
        for s in pool)
    for d in decisions:
        sym = d["stock"]
        q = quotes.get(sym)
        if not q:
            print(f"[warn] {sym} 行情缺失（停牌?），跳过")
            log_blocked(today, sym, "停牌/无行情，显式屏蔽")
            continue
        if is_one_word_board(q):
            print(f"[warn] {sym} 一字板（open=h=l），无法成交，屏蔽")
            log_blocked(today, sym, "一字板无法成交")
            continue
        if d["signal"] == "sell":
            pos = state["positions"].get(sym)
            if not pos or pos["shares"] <= 0:
                continue
            if q.get("pct") is not None and q["pct"] >= LIMIT_UP_PCT:
                print(f"[warn] {sym} 涨停不卖")
                log_blocked(today, sym, "涨停挂单无法成交")
                continue
            amount = pos["shares"] * q["price"]
            fee = max(amount * COMMISSION_RATE, MIN_COMMISSION) + amount * STAMP_TAX
            state["cash"] += amount - fee
            logs.append({"date": today, "stock": sym, "action": "sell", "price": q["price"],
                         "shares": pos["shares"], "amount": round(amount, 2),
                         "leverage": d["leverage"], "reason": d["reason"]})
            if "个股止损" in str(d.get("reason", "")):
                stop_log = DATA_DIR / "stop_loss_log.csv"
                pd.DataFrame([{"date": today, "stock": sym, "reason": d["reason"]}]).to_csv(
                    stop_log, index=False, encoding="utf-8-sig",
                    mode="a", header=not stop_log.exists())
            state["positions"].pop(sym, None)
            name = next((p.get("name", "") for p in (pool or [])
                         if p.get("symbol") == sym), "")
            pnl = round((q["price"] - float(pos["cost"])) * pos["shares"], 2)
            alert.notify("自动卖出",
                         f"{name}({sym}) 卖出{pos['shares']}股 @{q['price']} "
                         f"金额{amount:.0f} 盈亏{pnl:+.0f} 原因:{d['reason']}")
        elif d["signal"] == "buy":
            if _stop_cooled(sym, today):
                print(f"[warn] {sym} 止损冷却期（{STOP_COOLDOWN_DAYS}日），跳过买入")
                log_blocked(today, sym, "止损冷却期")
                continue
            if q.get("pct") is not None and q["pct"] <= LIMIT_DOWN_PCT:
                print(f"[warn] {sym} 跌停不买")
                log_blocked(today, sym, "跌停挂单无法成交")
                continue
            budget = min(total_value * MAX_POSITION_RATIO, state["cash"])
            if budget <= MIN_COMMISSION:
                continue
            shares = (budget * 0.999) / q["price"] // 100 * 100
            if shares <= 0:
                continue
            amount = shares * q["price"]
            fee = max(amount * COMMISSION_RATE, MIN_COMMISSION)
            if amount + fee > state["cash"]:
                continue
            state["cash"] -= amount + fee
            state["positions"][sym] = {"shares": shares, "cost": round(amount / shares, 3),
                                        "leverage": d["leverage"]}
            logs.append({"date": today, "stock": sym, "action": "buy", "price": q["price"],
                         "shares": shares, "amount": round(amount, 2),
                         "leverage": d["leverage"], "reason": d["reason"]})


def _top_leverage(decisions, positions):
    """熔断判定用杠杆 = max(当日决策杠杆, 持仓杠杆)。
    持仓期无新决策（全 hold）时仍保持买入时的杠杆敞口，回撤33%可正常触发熔断。"""
    d = max((int(x.get("leverage", 1)) for x in decisions), default=1)
    p = max((int(x.get("leverage", 1)) for x in positions.values()), default=1)
    return max(d, p)


def load_previous_decisions(today):
    """返回 (日期, DataFrame) 的上一份决策文件（早于 today 的最新一份）。"""
    files = sorted(DATA_DIR.glob("decision_*.csv"))
    for f in reversed(files):
        date_part = f.stem.replace("decision_", "")
        if date_part < today:
            return date_part, pd.read_csv(f, encoding="utf-8-sig", dtype={"stock": str})
    return None, None


def validate_predictions(today, quotes):
    """对上一交易日决策做预测校验，追加到 predictions.csv。
    规则：predict=up 且实际涨>0 → hit；predict=down 且实际跌<0 → hit；
          predict=flat 且 |涨跌幅| < FLAT_BAND → hit；其余 miss；predict=none 不参与。
    """
    prev_date, prev = load_previous_decisions(today)
    if prev is None:
        return
    records = []
    for _, r in prev.iterrows():
        pred = str(r.get("predict", ""))
        if pred == "none" or pred not in ("up", "down", "flat"):
            continue
        sym = r["stock"]
        q = quotes.get(sym)
        if not q:
            print(f"[warn] 预测校验 {prev_date} {sym} 行情缺失，跳过")
            continue
        pct = q.get("pct")
        if pct is None:
            print(f"[warn] 预测校验 {prev_date} {sym} 涨跌幅不可用，跳过")
            continue
        if pred == "up":
            hit = 1 if pct > 0 else 0
        elif pred == "down":
            hit = 1 if pct < 0 else 0
        else:
            hit = 1 if abs(pct) < FLAT_BAND else 0
        records.append({"pred_date": prev_date, "check_date": today, "stock": sym,
                        "predict": pred, "actual_pct": pct, "hit": hit})
    if not records:
        return
    vfile = DATA_DIR / "predictions.csv"
    pd.DataFrame(records).to_csv(vfile, index=False, encoding="utf-8-sig",
                                 mode="a", header=not vfile.exists())
    hits = sum(r["hit"] for r in records)
    print(f"[ok] 预测校验 {prev_date}: {hits}/{len(records)} 命中 "
          f"({hits / len(records):.0%})")


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    qfile = DATA_DIR / f"decision_{date_str}.csv"
    if not qfile.exists():
        print(f"[warn] 无决策文件 {qfile}，跳过撮合")
        return
    decisions = pd.read_csv(qfile, encoding="utf-8-sig", dtype={"stock": str}).to_dict("records")
    state = load_portfolio()
    pool = select_stock.load_pool(date_str)
    held = [{"symbol": sym} for sym, p in state["positions"].items()
            if p["shares"] > 0 and sym not in {s["symbol"] for s in pool}]
    pool = pool + held  # 持仓股票永远纳入报价/估值，避免退池后无法卖出
    quotes = latest_quote(pool)
    if not quotes:
        return
    validate_predictions(date_str, quotes)
    logs = []
    if state["cash"] >= INIT_CASH * 0.999 and not state["positions"]:
        print("[info] 首次运行，初始化模拟账户 10 万")
    if cb.in_cooldown():
        print(f"[circuit] 熔断冷却中（{cb.status_text()}），今日全部观望不交易")
        decisions = [dict(d, signal="hold", reason="熔断冷却中，暂停交易")
                     for d in decisions]
    else:
        stops = stop_loss_signal(state, quotes, date_str)
        if stops:
            print(f"[warn] 触发止损 {len(stops)} 只（成本回撤≥{STOP_LOSS_RATIO:.0%}）")
            decisions = decisions + stops
    run_orders(state, decisions, quotes, date_str, logs, pool)
    pfile = DATA_DIR / "portfolio.csv"
    rows = positions_rows(state, date_str, quotes, pool)
    pd.DataFrame(rows).to_csv(pfile, index=False, encoding="utf-8-sig",
                              mode="a", header=not pfile.exists())
    for s in rows:
        if s["shares"] > 0:
            print(f"[ok] {s['stock']} 持仓{s['shares']:.0f}股 市值{s['market_value']} 总资产{s['total_value']}")
    if logs:
        lfile = DATA_DIR / "trade_log.csv"
        pd.DataFrame(logs).to_csv(lfile, index=False, encoding="utf-8-sig",
                                  mode="a", header=not lfile.exists())
        for l in logs:
            print(f"[trade] {l['action']} {l['stock']} {l['shares']:.0f}股 @{l['price']} → {l['amount']:.2f}")

    total_value = float(rows[-1]["total_value"]) if rows else state["cash"]
    top_leverage = _top_leverage(decisions, state["positions"])
    events = cb.check_circuit(date_str, total_value, peak_value_ever(), top_leverage)
    senti_score = _last_sentiment_score()
    cb.record_sentiment(senti_score)
    if cb.try_recover(date_str):
        print("[circuit] 冷却条件满足，恢复正常交易（杠杆上限1倍起步）")
        events.append("恢复正常交易")
    for e in events:
        print(f"[circuit] {e}")


def _last_sentiment_score() -> float:
    try:
        df = pd.read_csv(DATA_DIR / "daily_sentiment.csv", encoding="utf-8-sig")
        return float(df.iloc[-1]["senti_score"])
    except Exception:
        return 0.0


if __name__ == "__main__":
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    main(date_str)