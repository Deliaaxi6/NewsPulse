"""告警模块回归测试（4 用例）：Telegram 转义 / 脚本失败不阻断 / 脚本成功 / 双通道失败。"""
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import alert


def _run(**kw):
    r = mock.Mock()
    r.returncode = kw.get("rc", 0)
    r.stderr = kw.get("stderr", "")
    return r


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    with mock.patch("alert.telegram_push.send_text", return_value=False) as send, \
         mock.patch("alert.Path.exists", return_value=False):
        ok = alert.notify("告警标题", "详情 & 符号 <x>")
        check("推送脚本不存在时直连通道仍发送",
              send.called and ok is False)
        check("Telegram 内容 HTML 转义",
              "<b>告警标题</b>" in send.call_args[0][0]
              and "详情 &amp; 符号 &lt;x&gt;" in send.call_args[0][0],
              send.call_args[0][0])

    with mock.patch("alert.telegram_push.send_text", return_value=False), \
         mock.patch("alert.Path.exists", return_value=True), \
         mock.patch("alert.subprocess.run", return_value=_run(rc=1, stderr="boom")) as sp:
        ok = alert.notify("t", "m")
        check("推送脚本失败返回 False 不抛异常", ok is False)
        check("脚本命令含事件与项目",
              "--event" in sp.call_args[0][0] and
              "NewsPulse" in sp.call_args[0][0])

    with mock.patch("alert.telegram_push.send_text", return_value=False), \
         mock.patch("alert.Path.exists", return_value=True), \
         mock.patch("alert.subprocess.run", return_value=_run(rc=0)) as sp:
        ok = alert.notify("t", "m")
        check("脚本成功返回 True", ok is True)

    with mock.patch("alert.telegram_push.send_text",
                    side_effect=Exception("tg down")), \
         mock.patch("alert.Path.exists", return_value=True), \
         mock.patch("alert.subprocess.run", return_value=_run(rc=0)):
        ok = alert.notify("t", "m")
        check("直连通道异常不阻断脚本通道", ok is True)

    print(f"alert: {4 - fails}/4 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
