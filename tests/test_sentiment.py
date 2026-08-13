"""情绪分类回归测试（12 用例）：否定翻转 / 程度加权 / 复合负面词保护。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from filter_news import score_text, classify_text

CASES = [
    ("净利润大幅增长，业绩超预期", "bull", "常规利好+程度词"),
    ("营收增长放缓，增速承压", "bear", "削弱利好词翻转增长"),
    ("公司业绩不及预期，股价下跌", "bear", "复合负面词直接命中"),
    ("公司遭遇处罚，亏损扩大，立案调查，承压", "bear", "负面词+削弱词组合不翻转"),
    ("股东减持计划公告", "bear", "减持"),
    ("例行公告，无重大变化", "neutral", "中性词"),
    ("中标重大工程，金额创纪录", "bull", "中标+创纪录"),
    ("亏损扩大，收到处罚通知", "bear", "亏损扩大+处罚"),
    ("未能完成收购，业绩未达预期", "bear", "未达预期不被窗口内否定翻转"),
    ("否认业绩造假传闻", "bull", "否认翻转负面传闻"),
    ("", "neutral", "空文本"),
    ("回购股份，维护投资者信心", "bull", "回购"),
]


def main() -> int:
    fails = 0
    for text, expect, note in CASES:
        got = classify_text(text)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {note:28s} score={score_text(text):+.2f} -> {got} (expect {expect})")
    print(f"sentiment: {len(CASES) - fails}/{len(CASES)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())