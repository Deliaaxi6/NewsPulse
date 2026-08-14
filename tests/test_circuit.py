"""熔断器回归测试（10 用例）：触发阈值 / 杠杆条件 / 冷却推进 / 情绪恢复 / 防循环 / 杠杆锁。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import circuit_breaker as cb


def _reset(td: Path):
    cb.STATE_FILE = Path(td) / "circuit_state_test.json"
    cb.STATE_FILE.unlink(missing_ok=True)


def main() -> int:
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        _reset(Path(td))

        def check(name, cond, note=""):
            nonlocal fails
            fails += 0 if cond else 1
            print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

        st = cb.load_state()
        check("初始状态 normal", st["status"] == "normal" and st["repeat_cool"] == 0)

        events = cb.check_circuit("2026-08-03", 70000, 100000, 3)
        st = cb.load_state()
        check("回撤30%不触发(阈值33%)", st["status"] == "normal" and not events)

        events = cb.check_circuit("2026-08-03", 66000, 100000, 2)
        check("2倍杠杆不触发熔断", cb.load_state()["status"] == "normal" and not events)

        events = cb.check_circuit("2026-08-03", 66000, 100000, 3)
        st = cb.load_state()
        check("3倍杠杆回撤34%触发熔断", st["status"] == "cooling" and len(events) == 1,
              f"cool_start={st['cool_start']}")
        check("触发后 repeat_cool=1", st["repeat_cool"] == 1)
        check("首次冷却期5日", cb.cooling_days(st) == 5)

        cb.check_circuit("2026-08-04", 60000, 100000, 3)
        st = cb.load_state()
        check("冷却中推进 recovered_days", st["recovered_days"] == 1)

        cb.save_state({"status": "normal", "cool_start": None, "recovered_days": 0,
                       "pos_senti_days": 0, "repeat_cool": 1, "last_cool_date": "2026-08-03"})
        cb.check_circuit("2026-08-07", 60000, 100000, 3)
        st = cb.load_state()
        check("窗口内二次熔断冷却翻倍", st["repeat_cool"] == 2 and cb.cooling_days(st) == 10)

        cb.save_state({"status": "normal", "cool_start": None, "recovered_days": 0,
                       "pos_senti_days": 0, "repeat_cool": 1, "last_cool_date": "2026-08-01"})
        cb.check_circuit("2026-08-25", 60000, 100000, 3)
        st = cb.load_state()
        check("超窗口(交易日>10)不翻倍", st["repeat_cool"] == 1 and cb.cooling_days(st) == 5)

        old = cb.trading_days_between
        cb.trading_days_between = lambda a, b: 10
        check("窗口边界=10交易日判重复", cb._is_repeat("2026-08-01", "2026-08-25") is True)
        cb.trading_days_between = lambda a, b: 11
        check("窗口11交易日判非重复", cb._is_repeat("2026-08-01", "2026-08-25") is False)
        cb.trading_days_between = lambda a, b: None
        check("日历不可用降级自然日", cb._is_repeat("2026-08-03", "2026-08-07") is True)
        cb.trading_days_between = old

        cb.record_sentiment(0.1)
        cb.record_sentiment(-0.2)
        cb.record_sentiment(0.3)
        st = cb.load_state()
        check("连续情绪转正计数(负数清零)", st["pos_senti_days"] == 1)
        check("冷却中杠杆锁1倍", cb.leverage_cap() == 1)
        check("冷却中 in_cooldown=True", cb.in_cooldown() is True)

        cb.save_state({"status": "cooling", "cool_start": "2026-08-03", "recovered_days": 5,
                       "pos_senti_days": 1, "repeat_cool": 1, "last_cool_date": "2026-08-03"})
        ok = cb.try_recover("2026-08-10")
        check("冷却满但情绪只1日不恢复", not ok and cb.in_cooldown())

        cb.save_state({"status": "cooling", "cool_start": "2026-08-03", "recovered_days": 5,
                       "pos_senti_days": 2, "repeat_cool": 1, "last_cool_date": "2026-08-03"})
        ok = cb.try_recover("2026-08-10")
        st = cb.load_state()
        check("冷却满+情绪2日恢复", ok and st["status"] == "normal")
        check("恢复后杠杆解锁", cb.leverage_cap() == 99)

        cb.STATE_FILE.unlink(missing_ok=True)
    print(f"circuit: {14 - fails}/14 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())