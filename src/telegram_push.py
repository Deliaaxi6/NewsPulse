"""Telegram 推送（Phase 3）：日报摘要 → Bot API sendMessage。

- 密钥不硬编码：token/chat_id 从环境变量 NEWSPULSE_TG_TOKEN / NEWSPULSE_TG_CHAT_ID
  读取（config.py），未配置 → 跳过推送（fail-open，不阻断主流程）
- 国内网络需代理：默认走本地 Clash 混合端口 http://127.0.0.1:7897
  （实测 api.telegram.org 经此端口可达），可用 NEWSPULSE_TG_PROXY 覆盖或置空禁用
- 失败仅告警不抛异常（与 G8/邮件推送 fail-open 风格一致）
"""
import sys

import requests

from config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    TELEGRAM_API_BASE, TELEGRAM_PROXY)


def send_text(text: str, token=None, chat_id=None, proxies=None, timeout=20) -> bool:
    """发送文本消息。成功 True；未配置/失败 False（不抛异常）。"""
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
    try:
        r = requests.post(url, json=payload, proxies=proxies, timeout=timeout)
        if r.status_code == 200 and r.json().get("ok"):
            print("[ok] Telegram 推送成功")
            return True
        print(f"[warn] Telegram 推送失败: HTTP {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[warn] Telegram 推送异常: {e}")
    return False


def report_summary(date_str: str, score: float, total: int, pos: int, neg: int,
                   assets: float, decision_count: int,
                   buys: list | None = None) -> str:
    """日报摘要文本（HTML：<b> 加粗）。buys: 买入信号记录列表（含 stock/leverage/reason）。"""
    buys = buys or []
    head = (f"<b>NewsPulse 日报 {date_str}</b>\n"
            f"情绪分 {score:+.2f} · 利好 {pos} / 利空 {neg} · 新闻 {total}\n"
            f"总资产 {assets:,.0f} · 决策 {decision_count} 只")
    if buys:
        lines = [f"  {b['stock']} {b.get('leverage', 1)}倍 · {b['reason']}" for b in buys]
        return head + "\n<b>买入信号:</b>\n" + "\n".join(lines)
    return head + "\n无买入信号，观望为主"


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
