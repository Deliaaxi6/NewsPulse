"""LLM 覆盖率标注测试（8 用例）：classify 属性/CSV 列/报告展示/兼容旧调用。"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import filter_news
import daily_report


def _df(n=5):
    return pd.DataFrame([{"title": f"t{i}", "content": "利好 中标",
                          "related_stocks": "", "senti": "bull"}
                         for i in range(n)])


def test_classify_attr() -> int:
    fails = 0
    with mock.patch.object(filter_news.llm_sentiment, "classify_batch",
                           return_value={0: "bear", 1: "bull", 2: "neutral"}):
        df = filter_news.classify(_df(), "2099-01-01")
    ok = (df.llm_covered == 3 and list(df["senti"].iloc[:3]) == ["bear", "bull", "neutral"]
          and df["senti"].iloc[3] == "bull")
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] classify 附加 llm_covered 属性 -> {df.llm_covered} (expect 3)")
    return fails


def test_classify_no_llm() -> int:
    fails = 0
    with mock.patch.object(filter_news.llm_sentiment, "classify_batch", return_value={}):
        df = filter_news.classify(_df(), "2099-01-01")
    ok = df.llm_covered == 0 and (df["senti"] == "bull").all()
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] LLM 无结果 -> llm_covered=0 全规则 -> {df.llm_covered}")
    return fails


def test_summarize_columns() -> int:
    fails = 0
    s = filter_news.summarize(_df(), "2099-01-01", 3)
    ok = (s["llm_covered"] == 3 and s["llm_total"] == 5 and s["llm_ratio"] == 0.6)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] summarize 覆盖率列 -> {s.get('llm_ratio')} (expect 0.6)")
    return fails


def test_summarize_compat() -> int:
    fails = 0
    s = filter_news.summarize(_df(), "2099-01-01")
    ok = "llm_ratio" not in s and s["senti_score"] == 1.0
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 旧签名(backtest)不产生新列 -> {list(s.keys())}")
    return fails


def test_summarize_empty() -> int:
    fails = 0
    s = filter_news.summarize(pd.DataFrame(columns=["senti"]), "2099-01-01", 0)
    ok = s["llm_ratio"] == 0.0 and s["total_news"] == 0
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 空表 ratio=0 不除零 -> {s['llm_ratio']}")
    return fails


def _render_with_ratio(ratio):
    old = daily_report.DATA_DIR
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        daily_report.DATA_DIR = td
        try:
            pd.DataFrame([{"date": "2099-01-01", "senti_score": 0.3, "total_news": 5,
                           "pos_cnt": 4, "neg_cnt": 1, "neutral_cnt": 0,
                           "llm_covered": int(5 * ratio), "llm_total": 5,
                           "llm_ratio": ratio}]).to_csv(
                td / "daily_sentiment.csv", index=False, encoding="utf-8-sig")
            html = daily_report._fill(daily_report.PAGE, date="2099-01-01",
                                      score="+0.30", total=5, pos=4, neg=1,
                                      neu=f"0{(' · LLM 覆盖 ' + f'{ratio:.0%}') if ratio is not None else ''}",
                                      verdict="x", score_color="#4a9eff",
                                      bearish_banner="", assets="100,000",
                                      decision_count=0, decision_rows="",
                                      prediction_rows="", position_rows="",
                                      trade_rows="", cyq_rows="",
                                      chart_scripts="")
            out = td / "report_2099-01-01.html"
            out.write_text(html, encoding="utf-8")
            txt = out.read_text(encoding="utf-8")
            return txt
        finally:
            daily_report.DATA_DIR = old


def test_report_mixed_note() -> int:
    fails = 0
    txt = _render_with_ratio(0.6)
    ok = "LLM 覆盖 60%" in txt
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 报告标注混合口径 LLM 覆盖 60% -> {'LLM 覆盖 60%' in txt}")
    return fails


def test_report_full_note() -> int:
    fails = 0
    txt = _render_with_ratio(1.0)
    ok = "LLM 覆盖 100%" in txt
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 报告标注全覆盖 100% -> {'LLM 覆盖 100%' in txt}")
    return fails


def test_main_mixed_print(tmp: Path) -> int:
    fails = 0
    old = filter_news.DATA_DIR
    filter_news.DATA_DIR = tmp
    try:
        _df(5).to_csv(tmp / "news_2099-01-01.csv", index=False, encoding="utf-8-sig")
        with mock.patch.object(filter_news, "select_stock") as ms:
            ms.load_pool.return_value = []
            with mock.patch.object(filter_news.llm_sentiment, "classify_batch",
                                   return_value={0: "bull", 1: "bear"}):
                filter_news.main("2099-01-01")
        df = pd.read_csv(tmp / "daily_sentiment.csv", encoding="utf-8-sig")
        ok = (df.iloc[-1]["llm_covered"] == 2 and df.iloc[-1]["llm_ratio"] == 0.4)
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] main 写覆盖率列 -> {df.iloc[-1]['llm_ratio']} (expect 0.4)")
    finally:
        filter_news.DATA_DIR = old
    return fails


def main() -> int:
    fails = 0
    fails += test_classify_attr()
    fails += test_classify_no_llm()
    fails += test_summarize_columns()
    fails += test_summarize_compat()
    fails += test_summarize_empty()
    fails += test_report_mixed_note()
    fails += test_report_full_note()
    with tempfile.TemporaryDirectory() as td:
        fails += test_main_mixed_print(Path(td))
    print(f"llm_coverage: {8 - fails}/8 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())