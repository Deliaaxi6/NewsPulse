"""网络防护层（InStock 融入）：直连优先 + 多源轮换 + 代理隔离 + 源级熔断。

借鉴 InStock 的多代理/Cookie 防封思路，适配 NewsPulse 实际痛点：
本机 Windows 系统代理（注册表 127.0.0.1:7897）失效时会拦截所有请求
（urllib3 经 urllib.request.getproxies() 读注册表代理）。
- 每次网络调用前先 patch getproxies 返回空（直连）尝试；
- 直连失败 → 恢复原始代理重试一次；
- 多数据源轮换由调用方 try_chain 编排（如 东财→新浪→腾讯）；
- 源级熔断（参考 daily_stock_analysis data_provider CircuitBreaker）：
  单源连续失败 3 次 → 冷却 300s 内跳过该源，避免反复打不可用接口。

Cookie 注入说明：akshare 不提供 session 注入点，NewsPulse 请求频次极低
（每日一次、4 只股票），限流风险低于 InStock 全市场轮询，故不做 Cookie
伪装；此层聚焦"代理防护 + 源轮换"，宁缺毋假不伪装。
"""
import os
import time
from contextlib import contextmanager

PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")

_FAIL_THRESHOLD = 3
_COOLDOWN_SECONDS = 300.0

# 源健康状态：{源名: {"fails": int, "until": float}}（进程内共享，跨调用生效）
_source_health = {}


def _no_proxy():
    return {}


def reset_health():
    """清空源熔断状态（测试/诊断用）。"""
    _source_health.clear()


def _is_cooled(name: str) -> bool:
    """纯查询：是否处于冷却期（无副作用，避免误清计数）。"""
    h = _source_health.get(name)
    if not h:
        return False
    return time.time() < h["until"]


def _record_fail(name: str) -> None:
    now = time.time()
    h = _source_health.get(name)
    if h is None:
        h = _source_health[name] = {"fails": 0, "until": 0.0}
    if now < h["until"]:
        return  # 冷却期内不再累计
    h["fails"] += 1
    if h["fails"] >= _FAIL_THRESHOLD:
        h["until"] = now + _COOLDOWN_SECONDS
        print(f"[warn] 数据源 {name} 连续失败{_FAIL_THRESHOLD}次，熔断{_COOLDOWN_SECONDS:.0f}s")


def _record_ok(name: str) -> None:
    _source_health.pop(name, None)


@contextmanager
def direct_mode():
    """临时禁用代理（环境变量 + Windows 注册表 getproxies），退出时恢复原状。"""
    saved_env = {k: os.environ.get(k) for k in PROXY_ENV_KEYS}
    for k in PROXY_ENV_KEYS:
        os.environ.pop(k, None)

    import urllib.request
    saved_urllib = urllib.request.getproxies
    urllib.request.getproxies = _no_proxy

    saved_ru = None
    try:
        import requests.utils as ru
        saved_ru = ru.getproxies
        ru.getproxies = _no_proxy
    except ImportError:
        pass
    try:
        yield
    finally:
        urllib.request.getproxies = saved_urllib
        if saved_ru is not None:
            ru.getproxies = saved_ru
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def try_chain(label: str, callers: list, retries: int = 1) -> object:
    """按序尝试多个数据源可调用，全部失败抛最后一个异常。

    callers: [(源名, 可调用)，...]；每个源先直连尝试，失败恢复代理再试一次。
    返回第一个成功的结果。源级熔断：连续失败 3 次的源在冷却期内被跳过。
    """
    last_err = None
    for name, fn in callers:
        if _is_cooled(name):
            print(f"[warn] {label}/{name} 熔断冷却中，跳过")
            continue
        result, ok = None, False
        for attempt in range(retries + 1):
            try:
                if attempt == 0:
                    with direct_mode():
                        result = fn()
                else:
                    result = fn()
                ok = True
                break
            except Exception as e:
                last_err = e
                if "ProxyError" in type(e).__name__ or "proxy" in str(e).lower():
                    print(f"[warn] {label}/{name} 直连失败(代理相关): {e}")
                else:
                    print(f"[warn] {label}/{name} 失败: {e}")
        if ok:
            _record_ok(name)
            return result
        _record_fail(name)
    raise last_err