"""tg_watchdog.py — Telegram daemon 自愈兜底（cron 每 5 分钟，服务器 root 执行）。

信号：
  1. daemon 进程存活（pgrep telegram_control.py daemon）
  2. 日志心跳：logs/tg_bot.log mtime（daemon 心跳/消息/失败都会写日志，
     正常心跳周期 300s，超过 STALE_MAX_SEC 无写入视为轮询停滞）

动作：停滞/死亡 → systemctl restart newspulse-tg-bot + Telegram 告警。
防抖：RESTART_MIN_GAP 秒内最多重启 1 次（状态存 data/tg_watchdog_state.json）。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/opt/newspulse")
LOG = BASE / "logs" / "tg_bot.log"
STATE_FILE = BASE / "data" / "tg_watchdog_state.json"
RESTART_MIN_GAP = 600
STALE_MAX_SEC = 900


def _now() -> int:
    return int(time.time())


def _load_state() -> int:
    try:
        return int(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_restart", 0))
    except Exception:
        return 0


def _save_state(ts: int):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"last_restart": ts}), encoding="utf-8")
    except Exception as e:
        print(f"[warn] watchdog 状态写入失败: {e}")


def _daemon_alive() -> bool:
    try:
        out = subprocess.run(["pgrep", "-f", "telegram_control.py daemon"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return bool(out)
    except Exception:
        return False


def _alert(msg: str):
    try:
        env = dict(os.environ)
        for line in (BASE / "secrets.env").read_text(encoding="utf-8").splitlines():
            if line.startswith("export "):
                k, v = line[7:].split("=", 1)
                env[k] = v.strip().strip('"')
        import requests
        tok = env.get("NEWSPULSE_TG_TOKEN", "")
        chat = env.get("NEWSPULSE_TG_CHAT_ID", "")
        if tok and chat:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": msg}, timeout=15)
    except Exception as e:
        print(f"[warn] 告警发送失败: {e}")


def _restart(reason: str):
    try:
        subprocess.run(["systemctl", "restart", "newspulse-tg-bot"],
                       capture_output=True, timeout=30)
        _alert(f"[NewsPulse] watchdog 已重启 Telegram daemon：{reason}")
        print(f"[warn] watchdog 重启 daemon：{reason}")
    except Exception as e:
        print(f"[warn] 重启失败: {e}")
    _save_state(_now())


def main() -> int:
    now = _now()
    last = _load_state()
    if now - last < RESTART_MIN_GAP:
        return 0
    if not _daemon_alive():
        _restart("daemon 进程不存在")
        return 0
    if LOG.exists() and now - LOG.stat().st_mtime > STALE_MAX_SEC:
        _restart(f"日志心跳停滞 {now - LOG.stat().st_mtime:.0f}s")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())