"""LLM 新闻分类回归测试（9 用例）：未配置跳过 / 缓存幂等 / 成功映射 / 批失败降级 / 熔断 / 集成覆盖。"""
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import llm_sentiment as ls


def _call_ok(labels):
    resp = mock.Mock()
    resp.json.return_value = {"choices": [{"message": {"content": _fmt(labels)}}]}
    return resp


def _fmt(labels):
    import json
    return json.dumps([{"label": x, "confidence": 0.8} for x in labels], ensure_ascii=False)


def main() -> int:
    fails = 0
    import tempfile
    _tmp = tempfile.TemporaryDirectory()
    _old_data = ls.DATA_DIR
    ls.DATA_DIR = Path(_tmp.name)

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    rows = [{"text": f"新闻{i}"} for i in range(5)]

    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", ""), \
         mock.patch("llm_sentiment.requests.post") as post:
        out = ls.classify_batch(rows, "2099-01-01")
        check("未配置 key 跳过不调API", out == {} and not post.called)

    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", "k1"), \
         mock.patch("llm_sentiment.requests.post", return_value=_call_ok(
             ["bull", "bear", "neutral", "bull", "bear"])) as post:
        out = ls.classify_batch(rows, "2099-01-02")
        check("成功映射 bull/bear/neutral",
              out == {0: "bull", 1: "bear", 2: "neutral", 3: "bull", 4: "bear"}, str(out))
        check("按批调用(BATCH)", post.call_count == 1)

        out2 = ls.classify_batch(rows, "2099-01-02")
        check("同日重跑命中缓存不调API", out2 == out and post.call_count == 1)

    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", "k1"), \
         mock.patch("llm_sentiment.requests.post", side_effect=ConnectionError("timeout")), \
         mock.patch("llm_sentiment.alert.notify") as nt:
        out = ls.classify_batch(rows, "2099-01-03")
        check("单批失败降级(空结果保留规则)", out == {})
        check("单批失败触发降级告警", nt.call_count == 1
              and "降级" in nt.call_args[0][0], str(nt.call_args))

    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", "k1"), \
         mock.patch("llm_sentiment.requests.post", side_effect=ConnectionError("timeout")), \
         mock.patch("llm_sentiment.alert.notify") as nt:
        many = [{"text": f"n{i}"} for i in range(40)]
        out = ls.classify_batch(many, "2099-01-04")
        check("连续失败3批熔断(部分批次已尝试)", out == {})
        subjects = [c[0][0] for c in nt.call_args_list]
        check("熔断时降级+熔断双告警",
              subjects.count("LLM 分类降级") == 1 and "LLM 分类熔断" in subjects,
              str(subjects))

    resp_bad = mock.Mock()
    resp_bad.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", "k1"), \
         mock.patch("llm_sentiment.requests.post", return_value=resp_bad), \
         mock.patch("llm_sentiment.alert.notify") as nt:
        out = ls.classify_batch(rows, "2099-01-05")
        check("JSON 解析失败降级", out == {})
        check("JSON 失败告警", nt.call_count == 1, str(nt.call_count))

    import filter_news as fn
    import pandas as pd
    df = pd.DataFrame({"title": ["公司发布利好公告", "业绩不及预期"],
                       "content": ["增长强劲", "利润下滑"]})
    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", "k1"), \
         mock.patch("llm_sentiment.requests.post", return_value=_call_ok(["bear", "bull"])):
        out_df = fn.classify(df, "2099-01-06")
        check("LLM 覆盖规则结果(反转)",
              list(out_df["senti"]) == ["bear", "bull"], str(list(out_df["senti"])))

    with mock.patch("llm_sentiment.DEEPSEEK_API_KEY", ""):
        out_df = fn.classify(df, "2099-01-07")
        check("无 key 时保留关键词规则结果",
              list(out_df["senti"]) == ["bull", "bear"], str(list(out_df["senti"])))

    ls.DATA_DIR = _old_data
    _tmp.cleanup()
    print(f"llm_sentiment: {12 - fails}/12 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())