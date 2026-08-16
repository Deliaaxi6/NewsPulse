"""周复盘测试（7 用例）：周区间 / 情绪回放 / 指数涨跌 / 相关性统计 / 命中率 / 数据不足跳过 / 报告生成。"""
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import weekly_review as wr
import pandas as pd


def main() -> int:
    fails = 0
    tmp = Path(tempfile.mkdtemp())

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # 周区间（2026-08-14 周五所在周 → 周一 08-10 ~ 周日 08-16）
    m, s = wr._week_range(pd.Timestamp("2026-08-14").date())
    check("周区间 周一~周日", (m.isoformat(), s.isoformat()) == ("2026-08-10", "2026-08-16"),
          f"{m}~{s}")

    # 情绪回放：仅读取区间内文件，逐日 summarize
    old = wr.DATA_DIR
    wr.DATA_DIR = tmp
    for d, content in {
        "2026-08-10": "title,content\n利好,业绩大增\n",
        "2026-08-11": "title,content\n利空,高管减持\n",
        "2026-08-12": "title,content\n中性,公司公告\n",
    }.items():
        (tmp / f"news_{d}.csv").write_text(content, encoding="utf-8-sig")
    (tmp / "news_2026-08-17.csv").write_text("title,content\n利好,业绩大增\n",
                                             encoding="utf-8-sig")
    with mock.patch("weekly_review.filter_news.summarize",
                    side_effect=lambda df, d: {"senti_score": 0.5 if d == "2026-08-10"
                                               else (-0.5 if d == "2026-08-11" else 0.0),
                                               "total_news": 1}):
        rows = wr.load_daily_sentiment("2026-08-10", "2026-08-16")
    check("情绪回放 区间内 3 日", len(rows) == 3 and rows[0]["date"] == "2026-08-10",
          str(rows))

    # 指数涨跌（mock akshare 返回两日）
    idx_df = pd.DataFrame({"date": ["2026-08-10", "2026-08-11"],
                           "close": [100.0, 101.5]})
    with mock.patch("weekly_review.ak", create=True) as ak:
        ak.stock_zh_index_daily.return_value = idx_df
        idx = wr.load_index_daily("2026-08-10", "2026-08-11")
    check("指数涨跌计算", abs(idx["2026-08-11"] - 1.5) < 1e-9, str(idx))

    # 相关性 + 命中率：情绪 T vs 次日指数 T+1
    senti = [{"date": "2026-08-10", "score": 0.5, "news": 1},
             {"date": "2026-08-11", "score": -0.5, "news": 1},
             {"date": "2026-08-12", "score": 0.0, "news": 1},
             {"date": "2026-08-13", "score": 0.4, "news": 1}]
    idx = {"2026-08-11": 1.0, "2026-08-12": -1.0, "2026-08-13": 0.5}
    st = wr.stats(senti, idx)
    check("配对样本=3（末日本日无次日）", len(st["pairs"]) == 3, str(st["pairs"]))
    check("命中率=2/2（0.0 不计入信号日）", st["hit"] == 2 and st["hit_n"] == 2,
          f"hit={st['hit']}/{st['hit_n']}")
    check("Pearson r 计算", st["r"] is not None and -1 <= st["r"] <= 1, f"r={st['r']}")

    # 数据不足跳过（2 日 < 3）
    old_r = wr.REPORTS_DIR
    wr.REPORTS_DIR = tmp / "reports"
    wr.REPORTS_DIR.mkdir(exist_ok=True)
    senti2 = [{"date": "2026-08-10", "score": 0.5, "news": 1},
              {"date": "2026-08-11", "score": -0.5, "news": 1}]
    with mock.patch("weekly_review.load_daily_sentiment", return_value=senti2), \
         mock.patch("weekly_review.load_index_daily", return_value=idx), \
         mock.patch("weekly_review.send_report_tg"), \
         mock.patch("weekly_review.alert.notify") as nt:
        out = wr.weekly_review(pd.Timestamp("2026-08-14").date())
    check("数据不足跳过不生成", out is None, f"out={out}")
    check("跳过时通知", nt.call_count == 1 and "周复盘跳过" in nt.call_args[0][0],
          str(nt.call_args) if nt.call_args else "")

    # 报告生成 + 推送 + Telegram 摘要
    with mock.patch("weekly_review.load_daily_sentiment", return_value=senti), \
         mock.patch("weekly_review.load_index_daily", return_value=idx), \
         mock.patch("weekly_review.send_report_tg") as send, \
         mock.patch("weekly_review.telegram_push.send_text") as tg:
        out = wr.weekly_review(pd.Timestamp("2026-08-14").date())
    check("周复盘报告生成", out is not None and out.exists(),
          str(out) if out else "")
    check("推送调用", send.call_count == 1)
    check("Telegram 摘要推送", tg.call_count == 1
          and "周复盘" in tg.call_args[0][0]
          and "0.961" in tg.call_args[0][0] and "命中" in tg.call_args[0][0],
          tg.call_args[0][0] if tg.call_args else "")
    if out:
        html = out.read_text(encoding="utf-8")
        check("报告含相关性统计", "Pearson" in html and "命中率" in html)

    wr.DATA_DIR = old
    wr.REPORTS_DIR = old_r
    print(f"weekly_review: {10 - fails}/10 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
