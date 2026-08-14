"""Telegram 推送回归测试（11 用例）：未配置跳过 / 成功 / HTTP失败 / 异常 / 代理 / 摘要格式 / 频道。"""
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import telegram_push as tp


def _resp(status, ok=None, text=""):
    r = mock.Mock()
    r.status_code = status
    r.text = text
    if ok is not None:
        r.json.return_value = {"ok": ok}
    else:
        r.json.side_effect = ValueError("bad json")
    return r


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", ""), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", ""), \
         mock.patch("telegram_push.requests.post") as post:
        ok = tp.send_text("hi", token="", chat_id="")
        check("未配置 token 跳过不调API", ok is False and not post.called)

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", "c1"), \
         mock.patch("telegram_push.TELEGRAM_PROXY", "http://127.0.0.1:7897"), \
         mock.patch("telegram_push.requests.post", return_value=_resp(200, True)) as post:
        ok = tp.send_text("hi")
        check("成功响应 ok=True", ok is True)
        url = post.call_args[0][0]
        check("URL 含 bot token", url.endswith("/bott1/sendMessage"), url)
        kw = post.call_args[1]
        check("payload 含 chat_id/text/parse_mode",
              kw["json"]["chat_id"] == "c1" and kw["json"]["text"] == "hi"
              and kw["json"]["parse_mode"] == "HTML")
        check("代理参数正确传递", kw["proxies"] ==
              {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"})

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", "c1"), \
         mock.patch("telegram_push.TELEGRAM_PROXY", ""), \
         mock.patch("telegram_push.requests.post", return_value=_resp(500)) as post:
        ok = tp.send_text("hi")
        check("HTTP 500 返回 False 不抛异常", ok is False)
        check("代理空则不传 proxies", post.call_args[1].get("proxies") is None)

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", "c1"), \
         mock.patch("telegram_push.time.sleep"), \
         mock.patch("telegram_push.requests.post",
                    side_effect=[ConnectionError("SSL EOF"), ConnectionError("SSL EOF"),
                                 _resp(200, True)]) as post:
        ok = tp.send_text("hi")
        check("SSL 抖动重试 2 次后成功", ok is True and post.call_count == 3,
              f"calls={post.call_count}")

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", "c1"), \
         mock.patch("telegram_push.time.sleep"), \
         mock.patch("telegram_push.requests.post",
                    side_effect=ConnectionError("timeout")) as post:
        ok = tp.send_text("hi")
        check("网络异常重试后返回 False 不抛异常", ok is False and post.call_count == 3,
              f"calls={post.call_count}")

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", "c1"), \
         mock.patch("telegram_push.time.sleep"), \
         mock.patch("telegram_push.requests.post",
                    return_value=_resp(500)) as post:
        ok = tp.send_text("hi")
        check("HTTP 500 不重试", ok is False and post.call_count == 1,
              f"calls={post.call_count}")

    with mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.TELEGRAM_CHAT_ID", "c1"), \
         mock.patch("telegram_push.requests.post", return_value=_resp(200, False)):
        ok = tp.send_text("hi")
        check("ok=False 返回 False", ok is False)

    s = tp.report_summary("2026-08-14", 0.22, 371, 88, 42, 100000.0, 20)
    check("摘要无买入含关键字段",
          "2026-08-14" in s and "0.22" in s and "100,000" in s
          and "观望为主" in s and "<b>买入信号:</b>" not in s, s)
    s2 = tp.report_summary("2026-08-14", 0.62, 500, 200, 50, 120000.0, 20,
                           [{"stock": "秦安股份", "leverage": 3, "reason": "海龟突破"}])
    check("摘要含买入信号行",
          "买入信号" in s2 and "秦安股份" in s2 and "3倍" in s2 and "海龟突破" in s2, s2)

    with mock.patch("telegram_push.TELEGRAM_CHANNEL", ""), \
         mock.patch("telegram_push.requests.post") as post:
        ok = tp.send_to_channel("hi")
        check("频道未配置跳过不调API", ok is False and not post.called)

    with mock.patch("telegram_push.TELEGRAM_CHANNEL", "@newspulse_channel"), \
         mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.requests.post", return_value=_resp(200, True)) as post:
        ok = tp.send_to_channel("hi")
        check("频道已配置调用且 chat_id=频道",
              ok is True and post.call_args[1]["json"]["chat_id"] == "@newspulse_channel")

    with mock.patch("telegram_push.TELEGRAM_CHANNEL", "@newspulse_channel"), \
         mock.patch("telegram_push.TELEGRAM_BOT_TOKEN", "t1"), \
         mock.patch("telegram_push.requests.post", side_effect=ConnectionError("timeout")):
        ok = tp.send_to_channel("hi")
        check("频道推送失败返回 False 不抛异常", ok is False)

    print(f"telegram: {14 - fails}/14 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())