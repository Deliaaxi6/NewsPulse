"""① 新闻爬取：东财全球财经快讯 + 4只个股新闻（akshare，带重试降级）。"""
import sys
import time
import datetime as dt
import traceback

import pandas as pd

from config import DATA_DIR, STOCKS


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
    """东财全球财经快讯，只保留内容非空的行。"""
    import akshare as ak

    df = retry(ak.stock_info_global_em)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["发布时间", "标题", "摘要", "链接"]].copy()
    df.columns = ["time", "title", "content", "related_stocks"]
    df = df[df["content"].notna() & (df["content"] != "")]
    return df


def fetch_stock_news(symbol):
    """单只个股新闻（东财）。"""
    import akshare as ak

    try:
        df = retry(ak.stock_news_em, symbol=symbol)
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
    frames = [fetch_market_news()]
    for s in STOCKS:
        frames.append(fetch_stock_news(s["symbol"]))
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
        main(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
