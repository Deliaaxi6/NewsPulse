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

MAX_SCAN = 20  # 扫描上限（全池可能上百只，全扫行情请求过重）
DATE_FMT = "%Y%m%d"
# 全市场快照过滤（方案C）：排除 ST、涨幅 0~9.9%（不追已涨停）、量比>1.5、成交额>2亿
MARKET_PCT_MIN = 0.0
MARKET_PCT_MAX = 9.9
MARKET_VOL_RATIO = 1.5
MARKET_AMOUNT_MIN = 2e8


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


def _filter_market_df(df: pd.DataFrame) -> pd.DataFrame:
    """全市场快照本地过滤（纯函数，可单测）：非ST / 涨幅 0~9.9% / 量比>1.5 / 成交额>2亿。
    输入/输出均为东财 spot_em 快照列（代码/名称/涨跌幅/量比/成交额）。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "名称" in out.columns:
        out = out[~out["名称"].astype(str).str.contains("ST", na=False)]
    if "涨跌幅" in out.columns:
        out = out[(out["涨跌幅"] > MARKET_PCT_MIN) & (out["涨跌幅"] < MARKET_PCT_MAX)]
    if "量比" in out.columns:
        out = out[out["量比"] > MARKET_VOL_RATIO]
    if "成交额" in out.columns:
        out = out[out["成交额"] > MARKET_AMOUNT_MIN]
    return out


def _market_pool(date_str: str) -> list:
    """全市场快照过滤池（东财一次请求）：过滤后按成交额取前 MAX_SCAN。失败返回 []。"""
    import akshare as ak

    try:
        df = net_guard.try_chain("东财快照", [("em", lambda: ak.stock_zh_a_spot_em())])
        f = _filter_market_df(df)
        if f.empty:
            print("[warn] 全市场快照过滤后为空，仅用涨停池")
            return []
        f = f.sort_values("成交额", ascending=False).head(MAX_SCAN)
        return [{"code": _code(str(r["代码"])), "symbol": str(r["代码"]),
                 "name": str(r["名称"]), "lbc": 0, "seal_amount": 0.0,
                 "strategies": "", "score": 0, "source": "market"}
                for _, r in f.iterrows()]
    except Exception as e:
        print(f"[warn] 全市场快照过滤失败: {e}，降级纯涨停池")
        return []


def _merge_pools(zt: list, mk: list) -> list:
    """涨停池与全市场过滤池合并去重（涨停池优先），按 连板数/封板资金 排序。
    纯函数，可单测。返回 records 列表。"""
    merged = {r["symbol"]: r for r in zt}
    for r in mk:
        merged.setdefault(r["symbol"], r)
    return sorted(merged.values(), key=lambda r: (-int(r.get("lbc", 0) or 0),
                                                  -float(r.get("seal_amount", 0) or 0)))[:MAX_SCAN]


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
    zt_rows = []
    for _, r in pool.iterrows():
        sym = str(r["代码"])
        zt_rows.append({
            "code": _code(sym),
            "symbol": sym,
            "name": str(r.get("名称", "")),
            "lbc": int(r.get("连板数", 0) or 0),
            "seal_amount": float(r.get("封板资金", 0) or 0),
            "strategies": "",
            "score": 0,
            "source": "zt",
        })
    merged = _merge_pools(zt_rows, _market_pool(date_str))
    rows = []
    for r in merged:
        sym = r["symbol"]
        hits = strategies.detect(sym)
        r["strategies"] = ";".join(hits)
        r["score"] = len(hits)
        rows.append(r)
    pd.DataFrame([{k: r[k] for k in ("code", "symbol", "name", "lbc",
                                     "seal_amount", "strategies", "score")} for r in rows]
                 ).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[ok] 选股 {len(rows)} 只（涨停池{base}"
          f"{'+全市场过滤' if any(x['source'] == 'market' for x in merged) else ''}）→ {out}")
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