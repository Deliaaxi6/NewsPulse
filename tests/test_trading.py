"""撮合安全回归测试（9 用例）：G5 停牌/一字板屏蔽 + 预测校验闭环。"""
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import sim_account

BOARD_CASES = [
    ({"open": 10.0, "high": 10.0, "low": 10.0, "pct": 10.0}, True, "标准一字板"),
    ({"open": 10.0, "high": 10.05, "low": 10.0, "pct": 9.5}, False, "T字板不误判"),
    ({"open": 10.0, "high": 10.0, "low": 10.0, "pct": 3.0}, False, "涨停未达板级"),
    ({"open": 10.0, "high": 10.0, "low": 10.0, "pct": -10.0}, True, "跌停一字板"),
    ({"open": None, "high": 10.0, "low": 10.0, "pct": 10.0}, False, "缺字段不误判"),
    ({}, False, "空行情不误判"),
]


def _make_decision_file(data_dir: Path, date_str: str, records):
    df = pd.DataFrame(records)
    df.to_csv(data_dir / f"decision_{date_str}.csv", index=False, encoding="utf-8-sig")


def test_predict_validation(tmp: Path) -> int:
    """validate_predictions：决策文件 T-1 日存在 → 按规则命中/未命中，none 跳过。"""
    fails = 0
    rows = [
        {"date": "2026-08-11", "stock": "600519", "signal": "buy", "leverage": 2,
         "predict": "up", "confidence": 0.8},
        {"date": "2026-08-11", "stock": "000858", "signal": "buy", "leverage": 2,
         "predict": "down", "confidence": 0.8},
        {"date": "2026-08-11", "stock": "601318", "signal": "hold", "leverage": 1,
         "predict": "flat", "confidence": 0.5},
        {"date": "2026-08-11", "stock": "600036", "signal": "buy", "leverage": 2,
         "predict": "up", "confidence": 0.8},
    ]
    _make_decision_file(tmp, "2026-08-11", rows)
    quotes = {"600519": {"pct": 1.2}, "000858": {"pct": -0.8},
              "601318": {"pct": 0.5}, "600036": {"pct": -2.0}}
    old = sim_account.DATA_DIR
    sim_account.DATA_DIR = tmp
    try:
        sim_account.validate_predictions("2026-08-12", quotes)
    finally:
        sim_account.DATA_DIR = old
    pf = tmp / "predictions.csv"
    if not pf.exists():
        print("[FAIL] 预测校验未生成 predictions.csv")
        return 1
    df = pd.read_csv(pf, encoding="utf-8-sig", dtype={"stock": str})
    if len(df) != 4:
        print(f"[FAIL] predictions.csv 应为4行，实际 {len(df)}")
        fails += 1
    expect = {"600519": 1, "000858": 1, "601318": 1, "600036": 0}
    for row in rows:
        stock = str(row["stock"])
        got = int(df[df["stock"].astype(str) == stock].iloc[0]["hit"])
        ok = got == expect[stock]
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 预测校验 {row['predict']:5s} {stock} "
              f"hit={got} (expect {expect[stock]})")
    _make_decision_file(tmp, "2026-08-12", [
        {"date": "2026-08-12", "stock": "600519", "signal": "hold", "leverage": 1,
         "predict": "none", "confidence": 0.0}
    ])
    pf.unlink()
    try:
        sim_account.DATA_DIR = tmp
        sim_account.validate_predictions("2026-08-13", quotes)
    finally:
        sim_account.DATA_DIR = old
    if pf.exists():
        print("[FAIL] predict=none 不应生成记录")
        fails += 1
    else:
        print("[OK] predict=none 跳过（不污染记录）")
    return fails


def main() -> int:
    fails = 0
    for q, expect, note in BOARD_CASES:
        got = sim_account.is_one_word_board(q)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 一字板 {note:12s} -> {got} (expect {expect})")
    with tempfile.TemporaryDirectory() as td:
        fails += test_predict_validation(Path(td))
    print(f"trading: {10 - fails}/10 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())