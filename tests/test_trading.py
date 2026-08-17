"""撮合安全回归测试（9 用例）：G5 停牌/一字板屏蔽 + 预测校验闭环。"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

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


def test_stop_loss(tmp: Path) -> int:
    """个股止损（方案A）：成本回撤≥8% 生成止损决策；冷却期内禁止买入。"""
    fails = 0
    state = {"positions": {
        "600519": {"shares": 100, "cost": 10.0, "leverage": 1},   # 现价 9.1 → 回撤 9%
        "000858": {"shares": 100, "cost": 10.0, "leverage": 1},   # 现价 9.3 → 回撤 7%
        "601318": {"shares": 100, "cost": 10.0, "leverage": 2},   # 无行情
        "600036": {"shares": 0, "cost": 10.0, "leverage": 1},     # 空仓
        "000001": {"shares": 100, "cost": 0.0, "leverage": 1},    # 成本缺失
    }}
    quotes = {"600519": {"price": 9.1}, "000858": {"price": 9.3}}
    got = sim_account.stop_loss_signal(state, quotes, "2026-08-14")
    syms = {g["stock"] for g in got}
    ok = syms == {"600519"}
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 止损触发 回撤9%触发/7%不触发/无行情跳过/空仓跳过/零成本跳过 -> {syms}")
    d = next(g for g in got if g["stock"] == "600519")
    ok = d["signal"] == "sell" and "个股止损" in d["reason"] and d["leverage"] == 1
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 止损决策字段 signal/leverage/reason -> {d}")

    log = tmp / "stop_loss_log.csv"
    pd.DataFrame([{"date": "2026-08-07", "stock": "000002", "reason": "个股止损"},
                  {"date": "2026-08-14", "stock": "600000", "reason": "个股止损"}]
                 ).to_csv(log, index=False, encoding="utf-8-sig")
    old = sim_account.DATA_DIR
    sim_account.DATA_DIR = tmp
    try:
        cases = [
            ("600000", "2026-08-14", True, "当日止损 → 冷却"),
            ("600000", "2026-08-18", True, "止损后3个交易日 → 冷却"),
            ("600000", "2026-08-21", False, "止损后≥5个交易日 → 可买"),
            ("000002", "2026-08-14", False, "其他股票不受影响"),
        ]
        for sym, date_str, expect, note in cases:
            got = sim_account._stop_cooled(sym, date_str)
            ok = got == expect
            fails += 0 if ok else 1
            print(f"[{'OK' if ok else 'FAIL'}] 止损冷却 {note:20s} -> {got} (expect {expect})")
    finally:
        sim_account.DATA_DIR = old
    return fails


def test_sell_alert() -> int:
    """卖出（含止损）成交后推送告警；涨停不卖/无行情不成交时不告警。"""
    fails = 0
    pool = [{"symbol": "600519", "name": "贵州茅台"}]
    calls = []
    orig = sim_account.alert.notify
    sim_account.alert.notify = lambda *a, **k: calls.append(a)
    try:
        state = {"cash": 100000.0,
                 "positions": {"600519": {"shares": 100, "cost": 10.0, "leverage": 1}}}
        quotes = {"600519": {"price": 11.0, "pct": 2.0}}
        logs = []
        sim_account.run_orders(state, [{"stock": "600519", "signal": "sell",
                                        "leverage": 1, "reason": "个股止损"}],
                               quotes, "2026-08-14", logs, pool)
        ok = (len(calls) == 1 and "600519" in calls[0][1]
              and "贵州茅台" in calls[0][1] and "+100" in calls[0][1]
              and "个股止损" in calls[0][1])
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 卖出告警 含代码/名称/盈亏/原因 -> {calls[0][1] if calls else ''}")
        ok = len(logs) == 1 and "600519" not in state["positions"]
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 卖出成交 持仓移除/日志记录")

        calls.clear()
        state2 = {"cash": 100000.0,
                  "positions": {"600519": {"shares": 100, "cost": 10.0, "leverage": 1}}}
        sim_account.run_orders(state2, [{"stock": "600519", "signal": "sell",
                                         "leverage": 1, "reason": "个股止损"}],
                               {"600519": {"price": 11.0, "pct": 10.0}},
                               "2026-08-14", [], pool)
        ok = not calls and "600519" in state2["positions"]
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 涨停不卖 不成交不告警")

        calls.clear()
        state3 = {"cash": 100000.0,
                  "positions": {"600519": {"shares": 100, "cost": 10.0, "leverage": 1}}}
        sim_account.run_orders(state3, [{"stock": "600519", "signal": "sell",
                                         "leverage": 1, "reason": "个股止损"}],
                               {}, "2026-08-14", [], pool)
        ok = not calls and "600519" in state3["positions"]
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 行情缺失 不成交不告警")
    finally:
        sim_account.alert.notify = orig
    return fails


def test_pending_merge(td: Path) -> int:
    """Telegram 手动指令：到期合并、金额/股数限、卖出部分、回执、状态流转。"""
    import telegram_control as tc
    fails = 0

    def check(name, ok, extra=""):
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" ← {extra}" if not ok else ""))

    tc.PENDING_FILE = td / "pending_orders.csv"
    tc.OFFSET_FILE = td / "tg_offset.txt"
    tc._save_pending([
        {"id": 1, "target_date": "2026-08-13", "side": "buy", "stock": "600519",
         "qty_type": "amount", "qty": 3000.0, "status": "pending"},
        {"id": 2, "target_date": "2026-08-14", "side": "buy", "stock": "000858",
         "qty_type": "shares", "qty": 100.0, "status": "pending"},
        {"id": 3, "target_date": "2026-08-14", "side": "sell", "stock": "600519",
         "qty_type": "shares", "qty": 100.0, "status": "pending"},
        {"id": 4, "target_date": "2026-08-16", "side": "buy", "stock": "601318",
         "qty_type": "amount", "qty": 5000.0, "status": "pending"},  # 未来日：不执行
        {"id": 5, "target_date": "2026-08-13", "side": "buy", "stock": "601318",
         "qty_type": "amount", "qty": 5000.0, "status": "cancelled"},  # 已取消：不执行
    ])
    with mock.patch("sim_account.DATA_DIR", td):
        decisions, due = sim_account._merge_pending_orders([], "2026-08-15")
    check("到期筛选", len(due) == 3 and len(decisions) == 3,
          f"due={len(due)} dec={len(decisions)}")
    check("buy 金额限", decisions[0]["signal"] == "buy"
          and decisions[0]["cap_amount"] == 3000.0)
    check("buy 固定股数", decisions[1]["fixed_shares"] == 100.0)
    check("sell 部分卖出", decisions[2]["signal"] == "sell"
          and decisions[2]["sell_shares"] == 100.0)

    # run_orders 撮合：600519 buy 3000 元 + sell 100 股；000858 100 股
    pool = [{"symbol": "600519", "name": "贵州茅台"},
            {"symbol": "000858", "name": "五粮液"},
            {"symbol": "601318", "name": "中国平安"}]
    quotes = {"600519": {"price": 10.0, "open": 10.0, "high": 11.0, "low": 9.5,
                         "pct": 1.5},
              "000858": {"price": 20.0, "open": 20.0, "high": 21.0, "low": 19.5,
                         "pct": 2.0},
              "601318": {"price": 30.0, "open": 30.0, "high": 31.0, "low": 29.5,
                         "pct": 1.0}}
    state = {"cash": 100000.0, "positions": {"600519": {"shares": 500,
                                                        "cost": 9.0, "leverage": 1}}}
    logs = []
    with mock.patch("sim_account.DATA_DIR", td), mock.patch("sim_account.alert.notify"):
        sim_account.run_orders(state, decisions, quotes, "2026-08-15", logs, pool)
    check("买入 3000 元金额限", any(l["action"] == "buy" and l["stock"] == "600519"
          and 0 < l["amount"] <= 3000 and l["shares"] % 100 == 0 for l in logs),
          [f"{l['action']}{l['stock']}{l['amount']}" for l in logs])
    check("买入 100 股固定", any(l["action"] == "buy" and l["stock"] == "000858"
          and l["shares"] == 100 for l in logs))
    check("部分卖出 100 股", any(l["action"] == "sell" and l["stock"] == "600519"
          and l["shares"] == 100 for l in logs))
    check("卖出后余仓 600", state["positions"]["600519"]["shares"] == 600)

    # 系统信号与手动指令同日同股：买入累加 + 成本摊薄
    state2 = {"cash": 100000.0, "positions": {}}
    logs2 = []
    dec2 = [
        {"stock": "600519", "signal": "buy", "leverage": 1, "reason": "情绪买入"},
        {"stock": "600519", "signal": "buy", "leverage": 1,
         "reason": "Telegram 手动买入 [指令#9]", "cap_amount": 2000.0},
    ]
    with mock.patch("sim_account.DATA_DIR", td), mock.patch("sim_account.alert.notify"):
        sim_account.run_orders(state2, dec2, quotes, "2026-08-15", logs2, pool)
    pos2 = state2["positions"]["600519"]
    check("同日系统+手动买入累加", len(logs2) == 2
          and pos2["shares"] == 2900 + 100
          and abs(pos2["cost"] - 10.0) < 0.01,
          f"shares={pos2['shares']} cost={pos2['cost']} logs={len(logs2)}")

    # 回执与状态流转
    with mock.patch("sim_account.telegram_push.send_text") as tg:
        sim_account._notify_pending_results(logs, due)
    rows = tc._load_pending()
    check("到期指令标记 executed", all(r["status"] == "executed" for r in rows
          if r["id"] in (1, 2, 3)))
    check("未来/取消指令不动", rows[3]["status"] == "pending"
          and rows[4]["status"] == "cancelled")
    check("回执含成交明细", tg.call_count == 1 and "指令#1" in tg.call_args[0][0]
          and "已买入" in tg.call_args[0][0] and "已卖出" in tg.call_args[0][0],
          tg.call_args[0][0][:120] if tg.call_args else "")

    # 无成交 → 未成交回执
    tc._save_pending([{"id": 9, "target_date": "2026-08-13", "side": "buy",
                       "stock": "601318", "qty_type": "amount", "qty": 5000.0,
                       "status": "pending"}])
    with mock.patch("sim_account.telegram_push.send_text") as tg:
        sim_account._notify_pending_results([], [{"id": 9}])
    check("未成交回执", "未能成交" in tg.call_args[0][0])
    return fails


def main() -> int:
    fails = 0
    for q, expect, note in BOARD_CASES:
        got = sim_account.is_one_word_board(q)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 一字板 {note:12s} -> {got} (expect {expect})")
    for decisions, positions, expect, note in [
        ([{"leverage": 3}], {}, 3, "决策3倍持仓空"),
        ([{"leverage": 1}], {"600519": {"leverage": 3}}, 3, "持仓期hold保持3倍敞口"),
        ([], {}, 1, "无决策无持仓默认1倍"),
    ]:
        got = sim_account._top_leverage(decisions, positions)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 熔断杠杆 {note:14s} -> {got} (expect {expect})")
    with tempfile.TemporaryDirectory() as td:
        fails += test_predict_validation(Path(td))
    with tempfile.TemporaryDirectory() as td:
        fails += test_stop_loss(Path(td))
    with tempfile.TemporaryDirectory() as td:
        fails += test_pending_merge(Path(td))
    fails += test_sell_alert()
    print(f"trading: {27 - fails}/27 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())