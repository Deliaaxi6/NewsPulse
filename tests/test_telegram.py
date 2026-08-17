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
    total = 0

    def check(name, cond, note=""):
        nonlocal fails, total
        total += 1
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
    s3 = tp.report_summary("2026-08-14", -0.3, 371, 0, 19, 98000.0, 20)
    check("利空提醒 情绪<=-0.1 触发",
          "利空主导" in s3 and "-0.30" in s3 and "19" in s3, s3)
    s4 = tp.report_summary("2026-08-14", -0.3, 371, 0, 19, 98000.0, 20,
                           [{"stock": "秦安股份", "leverage": 1, "reason": "超跌反弹"}])
    check("利空提醒 有买入时仍附加",
          "利空主导" in s4 and "买入信号" in s4, s4)
    s5 = tp.report_summary("2026-08-14", -0.05, 371, 0, 19, 98000.0, 20)
    check("利空提醒 -0.05 不触发（阈值 -0.1）",
          "利空主导" not in s5, "")
    s6 = tp.report_summary("2026-08-14", -0.1, 371, 0, 19, 98000.0, 20)
    check("利空提醒 恰好 -0.1 触发（<=）",
          "利空主导" in s6, "")

    # --- reason 压缩（KPI 风摘要） ---
    long_reason = ("情绪0.33>0.3 且 华正新材涨10.00% | 个股情绪: +0.33(9条) | "
                   "技术面: KDJ超买/RSI超买/突破布林上轨 | "
                   "形态: 捉腰带线/收盘缺影线/十字/风高浪大线/陷阱/长脚十字 | "
                   "资金面: 两融余额回升+1.63%")
    cr = tp._compact_reason(long_reason)
    check("reason压缩 长列表截断", "等6种" in cr and "捉腰带线/收盘缺影线/十字" in cr, cr)
    check("reason压缩 短列表保留", "KDJ超买/RSI超买/突破布林上轨" in cr and "等3种" not in cr, cr)
    check("reason压缩 无冒号段保留", "华正新材涨10.00%" in cr, cr)
    check("reason压缩 空值", tp._compact_reason("") == "" and tp._compact_reason(None) == "")
    s7 = tp.report_summary("2026-08-14", 0.33, 361, 58, 12, 83240.0, 20,
                           [{"stock": "华正新材", "leverage": 1, "reason": long_reason}])
    check("KPI摘要 分区块行", "📊" in s7 and "😀" in s7 and "📰" in s7 and "💰" in s7, s7)
    check("KPI摘要 信号两行式", "▸ <b>华正新材</b> 1倍" in s7 and "等6种" in s7, s7)

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

    print(f"telegram: {total - fails}/{total} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())