"""除权除息处理测试（9 用例）：送转/派息/幂等去重/接口失败 fail-open/边界。"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import sim_account


def _state(cash=100000.0, positions=None):
    return {"cash": cash, "positions": positions or {}}


def _fhps_row(ex_date="2026-08-18", send=5.0, div=3.0, desc="10转5.00派3.00元(含税)"):
    return pd.DataFrame([{
        "除权除息日": ex_date, "送转股份-送转总比例": send,
        "现金分红-现金分红比例": div, "现金分红-现金分红比例描述": desc,
    }])


def _with_tmp(fn, *args, **kwargs):
    with tempfile.TemporaryDirectory() as td:
        old = sim_account.DATA_DIR
        sim_account.DATA_DIR = Path(td)
        try:
            return fn(*args, **kwargs)
        finally:
            sim_account.DATA_DIR = old


def test_no_positions() -> int:
    fails = 0
    with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row()) as m:
        events = sim_account.apply_corporate_actions("2026-08-18", _state())
    ok = events == [] and not m.called
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 无持仓跳过不查接口 -> {events} (expect [])")
    return fails


def test_no_match_date() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row(ex_date="2026-07-01")):
        events = sim_account.apply_corporate_actions("2026-08-18", state)
    ok = events == [] and state["positions"]["600519"]["shares"] == 100.0
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 除权日不匹配不处理 -> {events} (expect [])")
    return fails


def test_send_ratio() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row(send=5.0, div=0.0)):
        events = sim_account.apply_corporate_actions("2026-08-18", state)
    pos = state["positions"]["600519"]
    ok = (events and pos["shares"] == 150.0 and abs(pos["cost"] - 66.667) < 0.01
          and state["cash"] == 100000.0)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 10转5: 股数100->150 成本66.667 -> "
          f"shares={pos['shares']} cost={pos['cost']} (expect 150/66.667)")
    return fails


def test_cash_div() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row(send=0.0, div=3.0)):
        events = sim_account.apply_corporate_actions("2026-08-18", state)
    pos = state["positions"]["600519"]
    ok = (events and pos["shares"] == 100.0 and abs(pos["cost"] - 99.7) < 0.01
          and state["cash"] == 100030.0)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 10派3: 现金+30 成本-0.3 -> "
          f"cash={state['cash']} cost={pos['cost']} (expect 100030/99.7)")
    return fails


def test_send_plus_div() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row(send=5.0, div=3.0)):
        events = sim_account.apply_corporate_actions("2026-08-18", state)
    pos = state["positions"]["600519"]
    ok = (events and pos["shares"] == 150.0 and state["cash"] == 100030.0)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 送转+派息同日: 派息按旧股数 -> "
          f"shares={pos['shares']} cash={state['cash']} (expect 150/100030)")
    return fails


def test_idempotent() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row(send=5.0, div=3.0)):
        ev1 = sim_account.apply_corporate_actions("2026-08-18", state)
        ev2 = sim_account.apply_corporate_actions("2026-08-18", state)
    pos = state["positions"]["600519"]
    ok = (len(ev1) == 1 and ev2 == [] and pos["shares"] == 150.0
          and state["cash"] == 100030.0 and (sim_account.DATA_DIR / "corporate_actions_log.csv").exists())
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 同日重跑幂等(去重日志) -> ev1={len(ev1)} ev2={len(ev2)} "
          f"shares={pos['shares']} cash={state['cash']} (expect 1/0/150/100030)")
    return fails


def test_api_fail_open() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=None):
        events = sim_account.apply_corporate_actions("2026-08-18", state)
    ok = events == [] and state["positions"]["600519"]["shares"] == 100.0
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 接口失败 fail-open -> {events} (expect [])")
    return fails


def test_nan_fields() -> int:
    fails = 0
    row = pd.DataFrame([{"除权除息日": "2026-08-18", "送转股份-送转总比例": float("nan"),
                         "现金分红-现金分红比例": float("nan"),
                         "现金分红-现金分红比例描述": float("nan")}])
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account, "_load_fhps", return_value=row):
        events = sim_account.apply_corporate_actions("2026-08-18", state)
    pos = state["positions"]["600519"]
    ok = (events and pos["shares"] == 100.0 and state["cash"] == 100000.0)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] NaN 字段(无送转无派息)不崩溃 -> {events} (expect 1 event)")
    return fails


def test_log_write_fail() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 100.0, "leverage": 1}})
    with mock.patch.object(sim_account.pd.DataFrame, "to_csv", side_effect=OSError("disk full")):
        with mock.patch.object(sim_account, "_load_fhps", return_value=_fhps_row(send=5.0, div=0.0)):
            events = sim_account.apply_corporate_actions("2026-08-18", state)
    pos = state["positions"]["600519"]
    ok = (len(events) == 1 and pos["shares"] == 150.0)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 日志写入失败不中断调整 -> {events} (expect 1 event)")
    return fails


def main() -> int:
    fails = 0
    fails += test_no_positions()
    fails += test_no_match_date()
    fails += _with_tmp(test_send_ratio)
    fails += _with_tmp(test_cash_div)
    fails += _with_tmp(test_send_plus_div)
    fails += _with_tmp(test_idempotent)
    fails += _with_tmp(test_api_fail_open)
    fails += _with_tmp(test_nan_fields)
    fails += _with_tmp(test_log_write_fail)
    print(f"corporate: {9 - fails}/9 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())