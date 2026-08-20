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
import requests

from config import DATA_DIR
import fund_flow
import net_guard
import strategies
import alert

MAX_SCAN = 20  # 扫描上限（全池可能上百只，全扫行情请求过重）
DATE_FMT = "%Y%m%d"
# 全市场快照过滤（方案C）：排除 ST、涨幅 0~9.9%（不追已涨停）、量比>1.5、成交额>2亿
MARKET_PCT_MIN = 0.0
MARKET_PCT_MAX = 9.9
MARKET_VOL_RATIO = 1.5
MARKET_AMOUNT_MIN = 2e8
# 新浪全市场快照降级源（东财 clist 被拒时）：按涨幅排序分页拉取，1页100只，
# 60 页覆盖全 A 股（约 5400 只），空页自动提前停止
SINA_SPOT_PAGES = 60
SINA_SPOT_URL = ("http://vip.stock.finance.sina.com.cn/quotes_service/api/"
                 "json_v2.php/Market_Center.getHQNodeData")
# 东财 clist 备用子域（82.push2 出口被封时轮换；走 mihomo 负载均衡组约半节点可用）
EM_ALT_HOSTS = ("83.push2", "push2delay")
EM_CLIST_FIELDS = "f2,f3,f5,f6,f10,f12,f14"
EM_CLIST_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
EM_CLIST_PAGES = 60  # fid=f3 涨幅降序前 60 页（6000 只，全量覆盖 A 股含极端普涨日），空页提前停


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
    """与 config.STOCKS 的 code 格式一致：6 开头→XSHG（含科创板 688）、0/3→XSHE（含创业板）、
    其余（北交所 4/8/920 开头）→BJ。"""
    if sym.startswith("6"):
        return f"{sym}.XSHG"
    if sym.startswith(("0", "3")):
        return f"{sym}.XSHE"
    return f"{sym}.BJ"


def _validate_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """早盘 0 值校验（宁缺毋假）：涨跌幅/量比/成交额任一列 0 值占比 >95%
    → 视为行情未生成（9:05 早盘新浪/东财常见），抛 ValueError 由 try_chain
    判定该源失败自动切下一源，全部失败走涨停池兜底。全 NaN/缺列/空表放行。"""
    if df is None or df.empty:
        return df
    for col in ("涨跌幅", "量比", "成交额"):
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if s.isna().all():
            continue
        zero_ratio = (s.fillna(0) == 0).mean()
        if zero_ratio > 0.95:
            raise ValueError(f"{col} 0值占比 {zero_ratio:.0%}，疑似早盘行情未生成，源不可用")
    return df


def _pct_max(code: str) -> float:
    """板块动态涨幅上限（不追已涨停）：主板 9.9、创业板/科创板 19.9、北交所 29.9。"""
    if code.startswith(("300", "301", "688", "689")):
        return 19.9
    if code.startswith(("4", "8", "920")):
        return 29.9
    return 9.9


def _filter_market_df(df: pd.DataFrame) -> pd.DataFrame:
    """全市场快照本地过滤（纯函数，可单测）：非ST / 涨幅 (0, 板块涨停上限) / 量比>1.5 / 成交额>2亿。
    输入/输出均为东财 spot_em 快照列（代码/名称/涨跌幅/量比/成交额）。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "名称" in out.columns:
        out = out[~out["名称"].astype(str).str.contains("ST", na=False)]
    if "涨跌幅" in out.columns and "代码" in out.columns:
        out = out[(out["涨跌幅"] > MARKET_PCT_MIN)
                  & (out["涨跌幅"] < out["代码"].astype(str).map(_pct_max))]
    if "量比" in out.columns:
        out = out[(out["量比"].isna()) | (out["量比"] > MARKET_VOL_RATIO)]
    if "成交额" in out.columns:
        out = out[out["成交额"] > MARKET_AMOUNT_MIN]
    return out


def _em_spot_alt(hosts: tuple) -> pd.DataFrame:
    """东财全市场快照备用子域（83.push2 / push2delay 轮换）：fid=f3 涨幅降序翻页，
    每页失败自动换下一个子域重试（应对 mihomo 负载均衡节点随机性），
    转换为东财 spot_em 列结构。全部翻页失败抛异常。"""
    import json

    rows = []
    for page in range(1, EM_CLIST_PAGES + 1):
        got = False
        for i, host in enumerate(hosts):
            try:
                params = {"pn": page, "pz": 100, "po": 1, "np": 1,
                          "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                          "fltt": 2, "invt": 2, "fid": "f3",
                          "fs": EM_CLIST_FS, "fields": EM_CLIST_FIELDS}
                r = requests.get(f"https://{host}.eastmoney.com/api/qt/clist/get",
                                 params=params, timeout=30)
                r.raise_for_status()
                diff = (json.loads(r.text).get("data") or {}).get("diff") or []
                if not diff:
                    if rows:
                        return _to_em_df(rows)  # 翻页自然结束（股票数不足 6000 只）
                    raise ValueError("东财备用快照为空")
                rows.extend(diff)
                got = True
                break
            except Exception:
                if i == len(hosts) - 1:
                    raise ValueError(f"东财备用快照翻页失败 page={page}")
        if not got:
            raise ValueError(f"东财备用快照翻页失败 page={page}")
    return _to_em_df(rows)


def _to_em_df(rows: list) -> pd.DataFrame:
    """clist diff 行列表 → 东财 spot_em 列结构（纯函数，可单测）。"""
    df = pd.DataFrame(rows)
    return _validate_snapshot(pd.DataFrame({
        "代码": df["f12"].astype(str),
        "名称": df["f14"].astype(str),
        "涨跌幅": pd.to_numeric(df.get("f3"), errors="coerce"),
        "量比": pd.to_numeric(df.get("f10"), errors="coerce"),
        "成交额": pd.to_numeric(df.get("f6"), errors="coerce"),
    }))


def _sina_spot() -> pd.DataFrame:
    """新浪全市场快照（按涨幅排序取前 SINA_SPOT_PAGES 页），转换为东财列结构。
    新浪源无量比字段（填 NaN，过滤时跳过）；amount 为万元（×1e4 转元）。
    数据全为空时抛异常（由 try_chain 判定源失败）。"""
    import json

    rows = []
    for page in range(1, SINA_SPOT_PAGES + 1):
        r = requests.get(SINA_SPOT_URL, params={"page": page, "num": 100,
                                                "sort": "changepercent",
                                                "asc": 0, "node": "hs_a"},
                         timeout=20)
        r.raise_for_status()
        data = json.loads(r.text)
        if not data:
            break
        rows.extend(data)
    if not rows:
        raise ValueError("新浪快照为空")
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "代码": df["symbol"].astype(str).str[-6:],
        "名称": df["name"].astype(str),
        "涨跌幅": pd.to_numeric(df.get("changepercent"), errors="coerce"),
        "量比": pd.to_numeric(df.get("volume_ratio"), errors="coerce"),
        "成交额": pd.to_numeric(df.get("amount"), errors="coerce").mul(1e4),
    })
    return _validate_snapshot(out)


def _market_pool(date_str: str) -> list:
    """全市场快照过滤池：东财官方子域 → 备用子域轮换 → 新浪分页降级（各源多次重试，
    覆盖 mihomo 负载均衡节点随机性）。全部源失败返回 []（涨停池兜底）。"""
    import akshare as ak

    try:
        df = net_guard.try_chain("东财快照",
                                 [("em", lambda: _validate_snapshot(ak.stock_zh_a_spot_em())),
                                  ("em_alt", lambda: _em_spot_alt(EM_ALT_HOSTS)),
                                  ("sina", _sina_spot)],
                                 retries=2)
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
        alert.notify("选股数据源降级", f"全市场快照获取失败: {e}，今日仅用涨停池")
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
        alert.notify("选股池为空", f"涨停池（基准 {base}）获取为空，今日无买入信号（写空池）")
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