"""Telegram 推送（Phase 3）：日报摘要 → Bot API sendMessage。

- 密钥不硬编码：token/chat_id 从环境变量 NEWSPULSE_TG_TOKEN / NEWSPULSE_TG_CHAT_ID
  读取（config.py），未配置 → 跳过推送（fail-open，不阻断主流程）
- 国内网络需代理：默认走本地 Clash 混合端口 http://127.0.0.1:7897
  （实测 api.telegram.org 经此端口可达），可用 NEWSPULSE_TG_PROXY 覆盖或置空禁用
- 失败仅告警不抛异常（与告警/推送 fail-open 风格一致）
"""
import sys
import time

import requests

from config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    TELEGRAM_API_BASE, TELEGRAM_PROXY, TELEGRAM_CHANNEL)

_MAX_ATTEMPTS = 3  # 网络/SSL 抖动重试（代理链路偶发 EOF）

BEARISH_SCORE = -0.1  # 情绪分低于此值 → 日报附加利空红色提醒


def send_text(text: str, token=None, chat_id=None, proxies=None, timeout=20) -> bool:
    """发送文本消息。成功 True；未配置/失败 False（不抛异常）。
    网络类异常（SSL/连接/超时）自动重试 2 次（间隔 2s/4s）；HTTP 业务错误不重试。"""
    token = token if token is not None else TELEGRAM_BOT_TOKEN
    chat_id = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("[info] Telegram 未配置（缺 token/chat_id），跳过推送")
        return False
    if proxies is None:
        proxies = ({"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY}
                   if TELEGRAM_PROXY else None)
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = requests.post(url, json=payload, proxies=proxies, timeout=timeout)
            if r.status_code == 200 and r.json().get("ok"):
                print("[ok] Telegram 推送成功")
                return True
            print(f"[warn] Telegram 推送失败: HTTP {r.status_code} {r.text[:200]}")
            return False  # HTTP 业务失败不重试
        except Exception as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                print(f"[warn] Telegram 推送异常（{attempt + 1}/{_MAX_ATTEMPTS - 1} 次重试）: {e}")
                time.sleep(2 * (attempt + 1))
    print(f"[warn] Telegram 推送异常（重试{_MAX_ATTEMPTS}次仍失败）: {last_exc}")
    return False


def send_to_channel(text: str, token=None, proxies=None, timeout=20) -> bool:
    """推送消息到频道（NEWSPULSE_TG_CHANNEL 配置的 @username/频道 ID）。
    频道未配置 → 跳过（fail-open）；复用 send_text，仅换 chat_id。"""
    if not TELEGRAM_CHANNEL:
        print("[info] Telegram 频道未配置（缺 NEWSPULSE_TG_CHANNEL），跳过频道推送")
        return False
    return send_text(text, token=token, chat_id=TELEGRAM_CHANNEL,
                     proxies=proxies, timeout=timeout)


_SEP = "━━━━━━━━━━━━"


def _compact_reason(reason: str, max_items: int = 3) -> str:
    """决策 reason 压缩：形态/技术面等斜杠列表只保留前 max_items 项 + 等N种，
    其余段落原样保留，段落间以 " · " 连接。纯函数，可单测。"""
    if not reason:
        return ""
    parts = []
    for seg in str(reason).split("|"):
        seg = seg.strip()
        if not seg:
            continue
        if ":" in seg:
            label, rest = seg.split(":", 1)
            rest = rest.strip()
            if "/" in rest:
                items = [x for x in rest.split("/") if x]
                if len(items) > max_items:
                    rest = "/".join(items[:max_items]) + f"等{len(items)}种"
            parts.append(f"{label.strip()}:{rest}")
        else:
            parts.append(seg)
    return " · ".join(parts)


def report_summary(date_str: str, score: float, total: int, pos: int, neg: int,
                   assets: float, decision_count: int,
                   buys: list | None = None) -> str:
    """日报摘要文本（KPI 分区块 + 买入信号精简行）。buys: {stock/leverage/reason}。"""
    buys = buys or []
    rows = [
        f"📊 <b>NewsPulse 日报 {date_str}</b>",
        _SEP,
        f"😀 情绪分 <b>{score:+.2f}</b> · 利好 {pos} / 利空 {neg}",
        f"📰 新闻 {total} 条 · 🎯 决策 {decision_count} 只",
        f"💰 总资产 <b>{assets:,.0f}</b>",
    ]
    if score <= BEARISH_SCORE:
        rows.append(f"⚠️ 利空主导（情绪分 {score:+.2f}，利空 {neg} / 利好 {pos}），注意持仓风险")
    rows.append(_SEP)
    if buys:
        rows.append(f"🟢 买入信号 ({len(buys)})")
        for b in buys:
            rows.append(f"▸ <b>{b['stock']}</b> {b.get('leverage', 1)}倍")
            rows.append(f"  {_compact_reason(b.get('reason', ''))}")
    else:
        rows.append("⚪ 无买入信号，观望为主")
    return "\n".join(rows)


def main(date_str=None, score=None, assets=None, buys=None):
    """CLI 自测入口：--date 日报摘要推送。"""
    import datetime as dt
    import pandas as pd
    from config import DATA_DIR
    date_str = date_str or dt.date.today().isoformat()
    senti = pd.read_csv(DATA_DIR / "daily_sentiment.csv", encoding="utf-8-sig")
    last = senti.iloc[-1]
    s = float(last["senti_score"]) if score is None else score
    pf = DATA_DIR / "portfolio.csv"
    assets = assets if assets is not None else (
        float(pd.read_csv(pf, encoding="utf-8-sig").iloc[-1]["total_value"])
        if pf.exists() else 100000.0)
    buys = buys or []
    msg = report_summary(date_str, s, int(last["total_news"]),
                         int(last["pos_cnt"]), int(last["neg_cnt"]),
                         assets, 0, buys)
    ok = send_text(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    sys.exit(main(date_str))
