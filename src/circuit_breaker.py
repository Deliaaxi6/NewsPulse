"""熔断器（核心安全阀）：3倍杠杆下市值跌超33% → 清仓+告警+冷却；恢复有防循环条件。

状态持久化于 data/circuit_state.json：
  status: normal | cooling
  cool_start: 熔断日
  recovered_days: 冷却期已过交易日数
  pos_senti_days: 连续情绪转正日数
  repeat_cool: 两次内熔断次数（防循环，冷却翻倍）
"""
import json
import datetime as dt

import pandas as pd

import alert
from config import DATA_DIR, LOGS_DIR
from fund_flow import trading_days_between

STATE_FILE = DATA_DIR / "circuit_state.json"
LOG_FILE = LOGS_DIR / "circuit.log"
CIRCUIT_TRIGGER_RATIO = 0.33       # 3倍杠杆下市值跌超33%触发
COOLDOWN_DAYS = 5                  # 基础冷却期（交易日）
RECOVERY_SENTI_DAYS = 2            # 恢复需连续情绪转正日数
RECOVERY_LEVERAGE_CAP = 1          # 恢复初期杠杆上限
REPEAT_PENALTY_MULTIPLIER = 2      # 冷却期翻倍倍率
STATE_COOLDOWN_WINDOW = 10         # 防循环窗口（交易日）


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "normal", "cool_start": None, "recovered_days": 0,
            "pos_senti_days": 0, "repeat_cool": 0, "last_cool_date": None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _log(msg: str):
    """熔断事件审计日志（触发/恢复/冷却推进），追加写 logs/circuit.log。"""
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception as e:
        print(f"[warn] 熔断日志写入失败: {e}")


def _is_repeat(last_cool_date: str, today: str) -> bool:
    """两次熔断是否落在防循环窗口内（交易日口径，日历不可用降级自然日）。"""
    span = trading_days_between(last_cool_date, today)
    if span is not None:
        return span <= STATE_COOLDOWN_WINDOW
    return (dt.date.fromisoformat(today) -
            dt.date.fromisoformat(last_cool_date)).days <= STATE_COOLDOWN_WINDOW


def check_circuit(today, total_value, peak_value, leverage):
    """每日收盘后调用。触发熔断或推进冷却/恢复。返回事件列表。"""
    state = load_state()
    events = []
    if state["status"] == "normal":
        if leverage >= 3 and peak_value > 0 and \
                (peak_value - total_value) / peak_value >= CIRCUIT_TRIGGER_RATIO:
            state["status"] = "cooling"
            state["cool_start"] = today
            state["recovered_days"] = 0
            state["pos_senti_days"] = 0
            if state["last_cool_date"] and _is_repeat(state["last_cool_date"], today):
                state["repeat_cool"] += 1
            else:
                state["repeat_cool"] = 1
            state["last_cool_date"] = today
            _log(f"熔断触发: 3倍杠杆下回撤{(peak_value-total_value)/peak_value:.1%}≥33% (repeat_cool={state['repeat_cool']})")
            events.append(f"熔断触发: 3倍杠杆下回撤{1-(total_value/peak_value if peak_value else 0):.1%}≥33%")
            alert.notify("熔断触发",
                         f"3倍杠杆下市值回撤{(peak_value-total_value)/peak_value:.1%}≥33%，"
                         f"已清仓并停止交易（冷却{cooling_days(state)}个交易日，"
                         f"连续{RECOVERY_SENTI_DAYS}日情绪转正后恢复）")
    else:
        state["recovered_days"] += 1
        _log(f"冷却推进 {state['recovered_days']}/{cooling_days(state)}日, 连续情绪转正{state['pos_senti_days']}/{RECOVERY_SENTI_DAYS}日")
    save_state(state)
    return events


def cooling_days(state: dict) -> int:
    """当前需要的冷却期（防循环翻倍）。"""
    mult = REPEAT_PENALTY_MULTIPLIER ** max(0, state.get("repeat_cool", 1) - 1)
    return COOLDOWN_DAYS * mult


def in_cooldown() -> bool:
    return load_state()["status"] == "cooling"


def record_sentiment(score: float):
    """每日情绪分记录：冷却期内连续转正计数。"""
    state = load_state()
    if state["status"] != "cooling":
        return state
    state["pos_senti_days"] = state["pos_senti_days"] + 1 if score > 0 else 0
    save_state(state)
    return state


def try_recover(today) -> bool:
    """冷却条件满足 → 恢复正常。返回是否恢复。"""
    state = load_state()
    if state["status"] != "cooling":
        return False
    needed = cooling_days(state)
    if state["recovered_days"] >= needed and state["pos_senti_days"] >= RECOVERY_SENTI_DAYS:
        state["status"] = "normal"
        state["cool_start"] = None
        state["recovered_days"] = 0
        state["pos_senti_days"] = 0
        save_state(state)
        _log("恢复: 冷却条件满足，恢复正常交易")
        return True
    return False


def leverage_cap() -> int:
    """当前杠杆上限（熔断后恢复初期锁1倍）。"""
    state = load_state()
    if state["status"] == "cooling":
        return RECOVERY_LEVERAGE_CAP
    return 99


def status_text() -> str:
    state = load_state()
    if state["status"] == "normal":
        return "normal"
    needed = cooling_days(state)
    return (f"cooling({state['recovered_days']}/{needed}日, "
            f"连续情绪转正{state['pos_senti_days']}/{RECOVERY_SENTI_DAYS}日)")


def main(today=None, total_value=0.0, peak_value=0.0, leverage=1):
    today = today or dt.date.today().isoformat()
    events = check_circuit(today, total_value, peak_value, leverage)
    recovered = try_recover(today)
    if events:
        for e in events:
            print(f"[circuit] {e}")
    if recovered:
        print("[circuit] 冷却条件满足，恢复正常交易")
    print(f"[circuit] 状态: {status_text()}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)