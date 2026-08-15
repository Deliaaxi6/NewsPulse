"""轻量告警：Telegram 私聊 + 邮件（复用 send_email.py 脚本）。

供数据源降级、自动卖出、异常事件等复用。两条通道独立 fail-open：
Telegram 失败不影响邮件、邮件失败不影响主流程，均只打印告警不抛异常。
"""
import subprocess
import sys
from pathlib import Path

import telegram_push
from config import (EMAIL_SCRIPT, EMAIL_CONFIG, EMAIL_TO, EMAIL_CC)


def _esc(text: str) -> str:
    """转义 Telegram HTML 特殊字符（send_text 固定 parse_mode=HTML）。"""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def notify(subject: str, message: str, event="error",
           to=None, cc=None) -> bool:
    """发送告警。subject 为标题（邮件主题/Telegram 首行），message 为详情。
    任一通道失败仅告警；返回 True 表示至少一个通道成功。"""
    ok = False
    to = to or EMAIL_TO
    cc = cc or EMAIL_CC
    try:
        if telegram_push.send_text(f"<b>{_esc(subject)}</b>\n{_esc(message)}"):
            ok = True
    except Exception as e:
        print(f"[warn] 告警 Telegram 通道失败: {e}")
    script = Path(EMAIL_SCRIPT)
    if script.exists():
        cmd = [sys.executable, str(script),
               "--to", to, "--cc", cc,
               "--event", event,
               "--project", "NewsPulse",
               "--message", f"{subject}: {message[:500]}",
               "--foreground"]
        if EMAIL_CONFIG:
            cmd += ["--config", EMAIL_CONFIG]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            if r.returncode == 0:
                ok = True
            else:
                print(f"[warn] 告警邮件推送失败: {r.stderr.strip()[:200]}")
        except Exception as e:
            print(f"[warn] 告警邮件推送异常: {e}")
    else:
        print(f"[info] 邮件脚本不存在 {script}（本地开发可忽略），仅 Telegram 通道")
    return ok


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    ok = notify("告警自检", "NewsPulse alert.notify 功能自检")
    sys.exit(0 if ok else 1)
