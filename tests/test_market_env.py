"""大盘环境护栏测试（DSA daily_market_context_guardrail 参考）：
弱势判定 / guard 软化 / 数据缺失宁缺毋假。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import market_env as me


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # --- 弱势判定 ---
    check("指数跌幅-2% 判弱", me.is_weak({"上证指数": -2.0, "深证成指": 0.5}, None))
    check("指数跌幅-1.2% 不判弱", not me.is_weak({"上证指数": -1.2}, None))
    check("指数+1% 但跌/涨=3 判弱", me.is_weak({"上证指数": 1.0}, {"up": 1000, "down": 3000}))
    check("指数+1% 家数正常不判弱", not me.is_weak({"上证指数": 1.0}, {"up": 3000, "down": 1000}))
    check("家数跌=0 不除零崩溃", not me.is_weak({"上证指数": 1.0}, {"up": 3000, "down": 0}))
    check("全空数据不判弱", not me.is_weak(None, None))

    # --- guard 软化 ---
    weak_env = {"weak": True, "note": "弱势"}
    s, c, sc, note = me.guard(weak_env, "buy", 0.9, 0.8)
    check("弱势 buy→hold", s == "hold", f"got={s}")
    check("弱势分数封顶0.5", sc == 0.5, f"got={sc}")
    check("弱势置信封顶0.5", c == 0.5, f"got={c}")
    check("弱势返回软化说明", note == "市场弱势已软化")
    check("弱势 sell 不软化", me.guard(weak_env, "sell", 0.9, -0.8)[0] == "sell")
    check("弱势 hold 保持", me.guard(weak_env, "hold", 0.3, 0.3)[0] == "hold")
    check("弱势 hold 分数仍封顶", me.guard(weak_env, "hold", 0.3, 0.9)[2] == 0.5)

    ok_env = {"weak": False, "note": "正常"}
    s, c, sc, note = me.guard(ok_env, "buy", 0.9, 0.8)
    check("正常环境原样返回", s == "buy" and c == 0.9 and sc == 0.8 and note is None)

    s, c, sc, note = me.guard(None, "buy", 0.9, 0.8)
    check("env=None 原样返回", s == "buy" and c == 0.9 and sc == 0.8 and note is None)

    return fails


if __name__ == "__main__":
    sys.exit(main())
