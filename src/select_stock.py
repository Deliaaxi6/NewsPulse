"""InStock 融入：综合选股（涨停池 → 策略模板扫描 → 每日观察池）。

每日收盘后拉东财涨停池（stock_zt_pool_em，基准日为 T-1 交易日），按连板数/封板资金
排序取前 MAX_SCAN 只，逐只跑 strategies.detect（10 个经典策略模板），写
data/select_YYYY-MM-DD.csv 供 fetch_news/decision/sim_account/daily_report 使用，
取代 config.STOCKS 硬编码观察池。空池/接口失败 fail-open（写空 CSV），不阻断后续步骤。

用法：python src/select_stock.py --date 2026-08-13
"""
import sys
import time
import datetime as dt

import pandas as pd

from config import DATA_DIR
import fund_flow
import net_guard
import strategies

MAX_SCAN = 20  # 涨停池扫描上限（全池可能上百只，全扫行情请求过重）
DATE_FMT = "%Y%m%d"


def _retry(func, tries=3, waits=(5, 15, 30), *args, **kwargs):
    for i in range(tries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"[warn] {func.__name__} 第{i+1}次失败: {e}，{waits[i]}s后重试")
            time.sleep(waits[i])


def _zt_pool(base_date: str) -> pd.DataFrame:
    """东财涨停池（base_date YYYYMMDD）。失败/空返回空 DataFrame。"""
    import akshare as ak

    try:
        df = net_guard.try_chain("东财涨停池", [("em", lambda: _retry(ak.stock_zt_pool_em, date=base_date))])
    except Exception as e:
        print(f"[warn] 涨停池获取失败: {e}")
        return pd.DataFrame()
    return df if df is not None and not df.empty else pd.DataFrame()


def _code(sym: str) -> str:
    """与 config.STOCKS 的 code 格式一致（600→沪 000→深）。"""
    return f"{sym}.XSHG" if sym.startswith("6") else f"{sym}.XSHE"


def select(date_str: str) -> None:
    """主流程：拉涨停池 → 排序截断 → 策略扫描 → 写 select_{date}.csv。"""
    if fund_flow.is_trading_day(date_str) is False:
        print(f"[info] {date_str} 非开市日（交易日历），跳过选股")
        return
    base = None
    for i in range(1, 8):
        d = (dt.date.fromisoformat(date_str) - dt.timedelta(days=i)).isoformat()
        if fund_flow.is_trading_day(d) is False:
            continue
        base = d
        break
    if base is None:
        print("[warn] 未找到基准交易日，跳过选股")
        return
    pool = None
    try:
        pool = _zt_pool(base.replace("-", ""))
    except Exception as e:
        print(f"[warn] 涨停池获取失败: {e}")
    out = DATA_DIR / f"select_{date_str}.csv"
    if pool is None or pool.empty:
        pd.DataFrame(columns=["code", "symbol", "name", "lbc", "seal_amount", "strategies", "score"]
                     ).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"[warn] 涨停池为空（{base}），写空池 {out}")
        return
    pool = pool.sort_values(["连板数", "封板资金"], ascending=False).head(MAX_SCAN)
    rows = []
    for _, r in pool.iterrows():
        sym = str(r["代码"])
        hits = strategies.detect(sym)
        rows.append({
            "code": _code(sym),
            "symbol": sym,
            "name": str(r.get("名称", "")),
            "lbc": int(r.get("连板数", 0) or 0),
            "seal_amount": float(r.get("封板资金", 0) or 0),
            "strategies": ";".join(hits),
            "score": len(hits),
        })
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[ok] 选股 {len(rows)} 只（涨停池{base}）→ {out}")
    for row in rows:
        print(f"  {row['symbol']} {row['name']} {row['lbc']}连板 策略[{row['strategies']}]")


def load_pool(date_str: str) -> list:
    """读取当日观察池（select_{date}.csv），不存在/为空返回 []。"""
    f = DATA_DIR / f"select_{date_str}.csv"
    if not f.exists():
        return []
    df = pd.read_csv(f, encoding="utf-8-sig",
                     dtype={"code": str, "symbol": str, "name": str})
    if df.empty:
        return []
    return df.fillna("").to_dict("records")


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    select(date_str)


if __name__ == "__main__":
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    main(date_str)