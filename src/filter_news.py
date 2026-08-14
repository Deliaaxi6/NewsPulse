"""② 关键词筛选与情绪分类：否定修饰 + 程度加权。"""
import sys
import datetime as dt

import pandas as pd

from config import (DATA_DIR, KEYWORDS_BULL, KEYWORDS_BEAR, KEYWORDS_NEUT,
                    NEGATION_GENERAL, NEGATION_BULL_ONLY,
                    INTENSIFY_STRONG, INTENSIFY_WEAK)
import llm_sentiment
import select_stock

NEG_WINDOW = 20


def score_text(text: str) -> float:
    """返回带符号情绪分：正=利好 负=利空 0=中性。
    否定词前后 NEG_WINDOW 字内、且与否定词不重叠的关键词命中极性翻转；
    同一命中只翻转一次；程度词加权。"""
    if not text:
        return 0.0
    hits = []
    for k in KEYWORDS_BULL:
        start = 0
        while True:
            pos = text.find(k, start)
            if pos < 0:
                break
            hits.append(("bull", pos, pos + len(k)))
            start = pos + 1
    for k in KEYWORDS_BEAR:
        start = 0
        while True:
            pos = text.find(k, start)
            if pos < 0:
                break
            hits.append(("bear", pos, pos + len(k)))
            start = pos + 1
    flipped = set()
    bull_net = sum(1 for pol, _, _ in hits if pol == "bull")
    bear_net = sum(1 for pol, _, _ in hits if pol == "bear")
    negated_prefixes = ("不及", "低于", "未达", "不达", "未能")
    for neg in NEGATION_GENERAL:
        npos = text.find(neg)
        if npos < 0:
            continue
        nend = npos + len(neg)
        for pol, hstart, hend in hits:
            if pol == "bear" and text[hstart:hstart + 2] in negated_prefixes:
                continue  # 复合负面词（不及预期/低于预期/未达预期）自身是否定形态，不再翻转
            if hstart < nend and hend > npos:
                continue  # 与否定词重叠的复合词不翻转
            near = (hend <= npos and npos - hend <= NEG_WINDOW) or \
                   (hstart >= nend and hstart - nend <= NEG_WINDOW)
            if not near:
                continue
            key = (pol, hstart)
            if key in flipped:
                continue
            flipped.add(key)
            if pol == "bull":
                bull_net -= 1
                bear_net += 1
            else:
                bear_net -= 1
                bull_net += 1
    for neg in NEGATION_BULL_ONLY:
        npos = text.find(neg)
        if npos < 0:
            continue
        nend = npos + len(neg)
        for pol, hstart, hend in hits:
            if pol == "bear":
                continue  # 削弱利好词不翻转负面关键词
            if hstart < nend and hend > npos:
                continue
            near = (hend <= npos and npos - hend <= NEG_WINDOW) or \
                   (hstart >= nend and hstart - nend <= NEG_WINDOW)
            if not near:
                continue
            key = (pol, hstart)
            if key in flipped:
                continue
            flipped.add(key)
            if pol == "bull":
                bull_net -= 1
                bear_net += 1
    strength = 1.0
    if any(w in text for w in INTENSIFY_STRONG):
        strength = 1.5
    elif any(w in text for w in INTENSIFY_WEAK):
        strength = 0.5
    return (bull_net - bear_net) * strength


def classify_text(text: str) -> str:
    score = score_text(text)
    if score > 0:
        return "bull"
    if score < 0:
        return "bear"
    return "neutral"


def classify(df: pd.DataFrame, date_str: str | None = None) -> pd.DataFrame:
    df = df.copy()
    df["senti"] = df["title"].fillna("") + " " + df["content"].fillna("")
    df["senti"] = df["senti"].apply(classify_text)
    llm = llm_sentiment.classify_batch(
        [{"text": t} for t in df["senti"]], date_str)
    for idx, label in llm.items():
        df.loc[idx, "senti"] = label
    return df


def summarize(df: pd.DataFrame, date_str: str) -> dict:
    total = len(df)
    pos = int((df["senti"] == "bull").sum())
    neg = int((df["senti"] == "bear").sum())
    neu = total - pos - neg
    score = round((pos - neg) / total, 4) if total else 0.0
    return {"date": date_str, "senti_score": score, "total_news": total,
            "pos_cnt": pos, "neg_cnt": neg, "neutral_cnt": neu}


def stock_sentiment(df: pd.DataFrame, pool_symbols: set) -> dict:
    """按个股新闻（related_stocks 为 6 位代码且在观察池内）分组聚合个股情绪分。
    市场新闻的 related_stocks 是链接（非 6 位代码）→ 不参与分组，宁缺毋假。
    返回 {sym: {score, count, pos, neg}}。"""
    res = {}
    if df is None or df.empty:
        return res
    sub = df[df["related_stocks"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    if not pool_symbols:
        return res
    sub = sub[sub["related_stocks"].isin(pool_symbols)]
    if sub.empty:
        return res
    for sym, g in sub.groupby("related_stocks"):
        pos = int((g["senti"] == "bull").sum())
        neg = int((g["senti"] == "bear").sum())
        n = len(g)
        res[sym] = {"score": round((pos - neg) / n, 4), "count": n,
                    "pos": pos, "neg": neg}
    return res


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    src = DATA_DIR / f"news_{date_str}.csv"
    if not src.exists():
        print(f"[warn] 无新闻文件 {src}，跳过")
        return
    df = pd.read_csv(src, encoding="utf-8-sig")
    df = classify(df, date_str)
    summary = summarize(df, date_str)
    pool = select_stock.load_pool(date_str)
    ss = stock_sentiment(df, {s["symbol"] for s in pool})
    if ss:
        rows = [{"date": date_str, "stock": k, "score": v["score"],
                 "count": v["count"], "pos": v["pos"], "neg": v["neg"]}
                for k, v in ss.items()]
        pd.DataFrame(rows).to_csv(DATA_DIR / f"stock_sentiment_{date_str}.csv",
                                  index=False, encoding="utf-8-sig")
        print(f"[ok] 个股情绪 {len(rows)} 只 → stock_sentiment_{date_str}.csv")
    out = DATA_DIR / "daily_sentiment.csv"
    old = pd.read_csv(out, encoding="utf-8-sig") if out.exists() else pd.DataFrame()
    if not old.empty:
        old = old[old["date"] != date_str]  # UPSERT 语义：同日重跑只保留最新一条
    new = pd.concat([old, pd.DataFrame([summary])], ignore_index=True)
    new.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[ok] 情绪分={summary['senti_score']} 利{summary['pos_cnt']}/空{summary['neg_cnt']}/中{summary['neutral_cnt']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    main(date_str)
