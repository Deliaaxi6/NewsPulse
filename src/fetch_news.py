"""① 新闻爬取：东财全球财经快讯 + 4只个股新闻（akshare，带重试降级）。

交易日历（adata）：非开市日直接早退，不空跑网络请求。
"""
import sys
import time
import datetime as dt
import traceback

import pandas as pd

from config import DATA_DIR
import fund_flow
import net_guard
import select_stock


def retry(func, tries=3, waits=(5, 15, 30), *args, **kwargs):
    for i in range(tries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"[warn] {func.__name__} 第{i+1}次失败: {e}，{waits[i]}s后重试")
            time.sleep(waits[i])


def fetch_market_news():
    """东财全球财经快讯，只保留内容非空的行。直连优先（系统代理常拦截东财）。"""
    import akshare as ak

    df = net_guard.try_chain("东财全球快讯", [("em", lambda: retry(ak.stock_info_global_em))])
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["发布时间", "标题", "摘要", "链接"]].copy()
    df.columns = ["time", "title", "content", "related_stocks"]
    df = df[df["content"].notna() & (df["content"] != "")]
    return df


def fetch_stock_news(symbol):
    """单只个股新闻（东财）。直连优先。"""
    import akshare as ak

    try:
        df = net_guard.try_chain(f"东财个股{symbol}", [("em", lambda: retry(ak.stock_news_em, symbol=symbol))])
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["发布时间", "新闻标题", "新闻内容"]].copy()
    df.columns = ["time", "title", "content"]
    df["related_stocks"] = symbol
    return df


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    opening = fund_flow.is_trading_day(date_str)
    if opening is False:
        print(f"[info] {date_str} 非开市日（交易日历），跳过新闻爬取")
        return
    if opening is None:
        print(f"[warn] 交易日历不可用，继续尝试爬取（避免误判非交易日）")
    frames = [fetch_market_news()]
    pool = select_stock.load_pool(date_str)
    if pool:
        for s in pool:
            frames.append(fetch_stock_news(s["symbol"]))
    else:
        print("[warn] 观察池为空（无选股结果），仅抓市场新闻")
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if df.empty:
        print("[warn] 新闻为空（可能非交易日）")
        return
    df = df.drop_duplicates(subset=["title"])
    out = DATA_DIR / f"news_{date_str}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[ok] 新闻 {len(df)} 条 → {out}")


if __name__ == "__main__":
    try:
        args = sys.argv[1:]
        date_str = None
        if args:
            if args[0] == "--date" and len(args) > 1:
                date_str = args[1]
            else:
                date_str = args[0]
        main(date_str)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
