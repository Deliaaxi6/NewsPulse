"""网络防护层测试（InStock 融入）：代理隔离/直连优先/多源轮换。"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import net_guard


class FakeProxyError(Exception):
    pass


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # --- direct_mode：临时移除并恢复代理环境变量 ---
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
    import urllib.request
    orig = urllib.request.getproxies
    with net_guard.direct_mode():
        check("直连中无代理变量", "HTTP_PROXY" not in os.environ and "HTTPS_PROXY" not in os.environ)
        check("直连中getproxies被禁用", urllib.request.getproxies() == {})
        import requests.utils as ru
        check("直连中requests无代理", ru.get_environ_proxies("https://x.com") == {})
    check("退出后代理恢复", os.environ.get("HTTP_PROXY") == "http://127.0.0.1:7890")
    check("退出后getproxies恢复", urllib.request.getproxies is orig)
    del os.environ["HTTP_PROXY"], os.environ["HTTPS_PROXY"]

    # --- try_chain：首源直接成功 ---
    r = net_guard.try_chain("t", [("a", lambda: "ok-a")])
    check("首源成功", r == "ok-a")

    # --- 首源代理失败(ProxyError)，次源成功 → 轮换 ---
    def bad():
        raise FakeProxyError("Unable to connect to proxy")
    r = net_guard.try_chain("t", [("a", bad), ("b", lambda: "ok-b")])
    check("代理失败轮换次源", r == "ok-b")

    # --- 全部失败 → 抛最后一个异常 ---
    try:
        net_guard.try_chain("t", [("a", bad), ("b", bad)])
        check("全失败抛异常", False)
    except FakeProxyError:
        check("全失败抛异常", True)

    # --- 直连失败但代理可用 → 恢复代理重试成功 ---
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            with net_guard.direct_mode() as _:
                pass
            raise FakeProxyError("proxy")
        return "ok-via-proxy"
    r = net_guard.try_chain("t", [("a", flaky)])
    check("直连失败恢复代理成功", r == "ok-via-proxy" and attempts["n"] == 2)

    # --- 非代理错误不重复报代理词 ---
    def other():
        raise ValueError("boom")
    try:
        net_guard.try_chain("t", [("a", other)])
        check("非代理异常传递", False)
    except ValueError:
        check("非代理异常传递", True)

    # --- 源级熔断：连续失败 3 次 → 冷却期跳过（DSA CircuitBreaker 参考）---
    net_guard.reset_health()

    def bad():
        raise ValueError("down")

    calls = {"c": 0}

    def counting_bad():
        calls["c"] += 1
        raise ValueError("down")

    for _ in range(3):
        try:
            net_guard.try_chain("t", [("src1", bad)])
        except ValueError:
            pass
    check("3次失败后进入冷却", net_guard._is_cooled("src1"))

    r = net_guard.try_chain("t", [("src1", counting_bad), ("src2", lambda: "ok-2")])
    check("冷却期跳过失败源走次源", r == "ok-2" and calls["c"] == 0, f"src1被调用{calls['c']}次")

    # --- 成功清除熔断计数 ---
    net_guard.reset_health()
    for _ in range(2):
        try:
            net_guard.try_chain("t", [("srcA", bad)])
        except ValueError:
            pass
    check("2次失败未熔断", not net_guard._is_cooled("srcA"))
    net_guard.try_chain("t", [("srcA", lambda: "ok")])
    try:
        net_guard.try_chain("t", [("srcA", bad)])  # 失败后计数从1开始，不熔断
    except ValueError:
        pass
    check("成功后计数清除", not net_guard._is_cooled("srcA"))

    # --- 冷却过期后恢复 ---
    net_guard.reset_health()
    for _ in range(3):
        try:
            net_guard.try_chain("t", [("srcB", bad)])
        except ValueError:
            pass
    net_guard._source_health["srcB"]["until"] = 0.0  # 模拟冷却过期
    check("冷却过期恢复", not net_guard._is_cooled("srcB"))

    print("\nnet_guard tests done.")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)