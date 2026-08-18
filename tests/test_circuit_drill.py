"""熔断真实路径演练测试（8 用例）：触发告警/冷却清仓/涨停保护/幂等/无告警噪声。"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import circuit_breaker as cb
import sim_account


def _state(cash=100000.0, positions=None):
    return {"cash": cash, "positions": positions or {}}


def _reset(tmp: Path):
    old_state, old_dir = cb.STATE_FILE, cb.STATE_FILE
    cb.STATE_FILE = tmp / "circuit_state.json"
    return old_state


def test_liquidation_positions() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 10.0, "leverage": 3},
                              "000858": {"shares": 200.0, "cost": 20.0, "leverage": 1},
                              "600036": {"shares": 0.0, "cost": 10.0, "leverage": 1}})
    rows = sim_account.circuit_liquidation(state)
    ok = (len(rows) == 2 and all(r["signal"] == "sell" for r in rows)
          and all("熔断清仓" in r["reason"] for r in rows)
          and rows[0]["leverage"] == 3)
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 冷却清仓决策: 全持仓sell(0股过滤) -> {rows}")
    return fails


def test_liquidation_empty() -> int:
    fails = 0
    rows = sim_account.circuit_liquidation(_state())
    ok = rows == []
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 空持仓清仓为空 -> {rows} (expect [])")
    return fails


def test_trigger_notify() -> int:
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        old = cb.STATE_FILE
        cb.STATE_FILE = Path(td) / "circuit_state.json"
        try:
            with mock.patch.object(cb.alert, "notify") as m:
                events = cb.check_circuit("2026-08-18", 65000.0, 100000.0, 3)
        finally:
            cb.STATE_FILE = old
    ok = (events and "熔断触发" in events[0] and m.called
          and "熔断触发" in str(m.call_args[0][0]) and "33%" in str(m.call_args[0][1]))
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 熔断触发发告警 -> events={events} notify={m.call_args}")
    return fails


def test_no_trigger_no_notify() -> int:
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        old = cb.STATE_FILE
        cb.STATE_FILE = Path(td) / "circuit_state.json"
        try:
            with mock.patch.object(cb.alert, "notify") as m:
                events = cb.check_circuit("2026-08-18", 70000.0, 100000.0, 3)
        finally:
            cb.STATE_FILE = old
    ok = events == [] and not m.called
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 未触发不发告警 -> {events} (expect [])")
    return fails


def test_cooldown_no_repeat_notify() -> int:
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        old = cb.STATE_FILE
        cb.STATE_FILE = Path(td) / "circuit_state.json"
        try:
            with mock.patch.object(cb.alert, "notify") as m:
                cb.check_circuit("2026-08-18", 65000.0, 100000.0, 3)
                events2 = cb.check_circuit("2026-08-19", 65000.0, 100000.0, 3)
        finally:
            cb.STATE_FILE = old
    ok = m.call_count == 1 and events2 == []
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 冷却推进不再告警 -> notify次数={m.call_count} events2={events2}")
    return fails


def test_liquidation_run_orders(tmp: Path) -> int:
    fails = 0
    old = sim_account.DATA_DIR
    sim_account.DATA_DIR = tmp
    pool = [{"symbol": "600519", "name": "贵州茅台"}]
    calls = []
    orig = sim_account.alert.notify
    sim_account.alert.notify = lambda *a, **k: calls.append(a)
    try:
        state = _state(positions={"600519": {"shares": 100.0, "cost": 10.0, "leverage": 3}})
        decisions = sim_account.circuit_liquidation(state)
        logs = []
        sim_account.run_orders(state, decisions,
                               {"600519": {"price": 6.5, "pct": -2.0}},
                               "2026-08-19", logs, pool)
        ok = ("600519" not in state["positions"]
              and len(logs) == 1 and "熔断清仓" in logs[0]["reason"]
              and not (tmp / "stop_loss_log.csv").exists()
              and any("600519" in c[1] and "熔断清仓" in c[1] for c in calls))
        fails += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 清仓成交: 持仓移除/日志/告警/不写止损冷却 -> {logs}")
    finally:
        sim_account.DATA_DIR = old
        sim_account.alert.notify = orig
    return fails


def test_liquidation_limit_up_block() -> int:
    fails = 0
    pool = [{"symbol": "600519", "name": "贵州茅台"}]
    state = _state(positions={"600519": {"shares": 100.0, "cost": 10.0, "leverage": 3}})
    decisions = sim_account.circuit_liquidation(state)
    logs = []
    sim_account.run_orders(state, decisions,
                           {"600519": {"price": 11.0, "pct": 10.0}},
                           "2026-08-19", logs, pool)
    ok = "600519" in state["positions"] and logs == []
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 清仓遇涨停不卖(保护) -> 持仓保留 {state['positions']}")
    return fails


def test_liquidation_idempotent() -> int:
    fails = 0
    state = _state(positions={"600519": {"shares": 100.0, "cost": 10.0, "leverage": 3}})
    rows1 = sim_account.circuit_liquidation(state)
    state["positions"].pop("600519", None)
    rows2 = sim_account.circuit_liquidation(state)
    ok = len(rows1) == 1 and rows2 == []
    fails += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] 清仓后幂等(无持仓不再卖) -> {len(rows1)}/{len(rows2)}")
    return fails


def main() -> int:
    fails = 0
    fails += test_liquidation_positions()
    fails += test_liquidation_empty()
    fails += test_trigger_notify()
    fails += test_no_trigger_no_notify()
    fails += test_cooldown_no_repeat_notify()
    with tempfile.TemporaryDirectory() as td:
        fails += test_liquidation_run_orders(Path(td))
    fails += test_liquidation_limit_up_block()
    fails += test_liquidation_idempotent()
    print(f"circuit_drill: {8 - fails}/8 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())