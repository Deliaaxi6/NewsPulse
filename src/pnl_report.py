"""盈亏日报（run_all 末尾独立步骤）：portfolio.csv 快照 → Telegram 推送当日盈亏。

口径（与账户撮合一致）：
- 每日总资产 = 当日现金 + Σ(持仓行 market_value)；portfolio 每行是全账户快照，
  空仓行 total_value=现金，必须按 shares>0 行累加市值，不能直接取单行 total。
- 累计盈亏 = 当日总资产 - INIT_CASH（含佣金/印花税后的净结果）。
- 浮动盈亏 = Σ(市值 - 成本×股数)，仅当前持仓。
- 今日盈亏 = 当日总资产 - 上一有数据交易日总资产。
- date_str 当日无数据 → 回落到最近有数据日（避免持仓/盈亏历史丢失后不推送）。
"""
import sys
import datetime as dt
from pathlib import Path

import pandas as pd

from config import DATA_DIR, INIT_CASH


def _read_grouped(date_str: str) -> dict:
    """按日期分组读取 portfolio.csv（含 BOM），返回 {date: {cash, mv_sum, cost_sum, rows}}。
    数据缺失/无文件返回 {}。"""
    p = DATA_DIR / "portfolio.csv"
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p, encoding="utf-8-sig", dtype={"stock": str} if "stock" in p.read_text(encoding="utf-8-sig")[:200] else None)
    except Exception as e:
        print(f"[warn] 盈亏日报读持仓失败: {e}")
        return {}
    df = df[df["date"].astype(str) <= date_str]
    if df.empty:
        return {}
    out = {}
    for d, g in df.groupby("date"):
        held = g[g["shares"].astype(float) > 0]
        out[str(d)] = {
            "cash": float(g.iloc[-1]["cash"]),
            "mv_sum": float(held["market_value"].sum()) if not held.empty else 0.0,
            "cost_sum": float((held["cost"] * held["shares"]).sum()) if not held.empty else 0.0,
            "rows": held.to_dict("records"),
        }
    return out


def pnl_summary(date_str: str) -> dict:
    """返回按截止日期的盈亏汇总。无数据返回 {}（fail-open，不推送不报错）。"""
    groups = _read_grouped(date_str)
    if not groups:
        return {}
    dates = sorted(groups)
    cur_date = dates[-1]
    cur = groups[cur_date]
    assets = cur["cash"] + cur["mv_sum"]
    prev_assets = None
    if len(dates) >= 2:
        prev = groups[dates[-2]]
        prev_assets = prev["cash"] + prev["mv_sum"]
    total_pnl = assets - INIT_CASH
    pnl_pct = total_pnl / INIT_CASH * 100
    day_pnl = (assets - prev_assets) if prev_assets is not None else 0.0
    day_pct = (day_pnl / prev_assets * 100) if prev_assets else 0.0
    positions = []
    for r in cur["rows"]:
        cost_total = float(r["cost"]) * float(r["shares"])
        positions.append({
            "stock": r["stock"], "shares": float(r["shares"]),
            "cost": float(r["cost"]), "price": float(r["market_value"]) / float(r["shares"]),
            "pnl": float(r["market_value"]) - cost_total,
        })
    return {
        "date": cur_date, "assets": assets, "cash": cur["cash"],
        "total_pnl": total_pnl, "pnl_pct": pnl_pct,
        "day_pnl": day_pnl, "day_pct": day_pct,
        "prev_date": dates[-2] if len(dates) >= 2 else None,
        "positions": positions, "position_count": len(positions),
    }


def _fmt(s: dict) -> str:
    """>>> 盈亏日报文本。整个账号为空持仓时报空仓。"""
    if not s:
        return ""
    lines = [
        f"📊 <b>盈亏日报 {s['date']}</b>",
        "──────────────",
        f"💰 总资产 <b>{s['assets']:,.0f}</b>",
        f"📈 累计盈亏 <b>{s['total_pnl']:+,.0f}</b> ({s['pnl_pct']:+.2f}%)",
    ]
    if s["prev_date"] is not None:
        lines.append(f"🔄 较 {s['prev_date']} 盈亏 <b>{s['day_pnl']:+,.0f}</b> ({s['day_pct']:+.2f}%)")
    else:
        lines.append("🔄 首个数据日，无环比")
    lines.append("──────────────")
    if s["positions"]:
        lines.append(f"持仓明细 ({s['position_count']} 只)")
        for p in s["positions"]:
            sign = "🟢" if p["pnl"] >= 0 else "🔴"
            lines.append(f"{sign} {p['stock']} {p['shares']:.0f}股 "
                         f"现价{p['price']:.2f} 浮盈<b>{p['pnl']:+.0f}</b>")
    else:
        lines.append("当前空仓，仅现金")
    lines.append(f"现金: {s['cash']:,.0f}")
    return "\n".join(lines)


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    s = pnl_summary(date_str)
    text = _fmt(s)
    if not text:
        print(f"[warn] 盈亏日报无数据，跳过推送（{date_str}）")
        return
    import telegram_push
    telegram_push.send_text(text)
    telegram_push.send_to_channel(text)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    args = sys.argv[1:]
    main(args[0] if args else None)