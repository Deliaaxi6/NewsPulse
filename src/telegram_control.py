"""Telegram 远程指令（Phase 4）：用户私聊命令 → 次日开盘价模拟成交。

- 单向推送 → 双向：getUpdates 短轮询（crontab 每 5 分钟拉取，无需常驻进程）
- 安全：仅接受 chat_id == TELEGRAM_CHAT_ID（本人）的消息；命令白名单；
  代码 6 位数字校验；撮合层（单票≤30%/现金/持仓）最终把关
- 执行时机：指令记 target_date=收到日，撮合日 T 执行所有 target_date < T 的
  pending 指令（周末指令 → 周一开盘价成交，与系统信号同一撮合路径）
- 命令：
  /buy <代码> <金额|股数股>   e.g. /buy 600519 5000 或 /buy 600519 100股
  /sell <代码> [股数]         缺省全卖；卖出不强制持仓校验（撮合层拒绝并回执）
  /status                   持仓/现金/待执行指令
  /cancel <id|all>           取消待执行指令
  /help                      命令说明
- 每命令回执（sendMessage 原 chat）；全部失败 fail-open 不抛异常
"""
import re
import sys
import time
import datetime as dt
from pathlib import Path

import requests
import pandas as pd

from config import (DATA_DIR, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    TELEGRAM_API_BASE, TELEGRAM_PROXY)
import telegram_push

CMD_RE = {
    "buy": re.compile(r"^/buy\s+(\d{6})(?:\s+(\d+(?:\.\d+)?)\s*(股)?)?$", re.I),
    "sell": re.compile(r"^/sell\s+(\d{6})(?:\s+(\d+(?:\.\d+)?))?", re.I),
    "status": re.compile(r"^/status\s*$", re.I),
    "cancel": re.compile(r"^/cancel\s+(all|\d+)\s*$", re.I),
    "help": re.compile(r"^/help\s*$", re.I),
}
MAX_ORDER_AMOUNT = 30000.0  # 单笔指令金额上限（模拟盘，撮合层单票≤30%≈3万）
PENDING_FILE = DATA_DIR / "pending_orders.csv"
OFFSET_FILE = DATA_DIR / "tg_offset.txt"


def _proxy():
    return {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY} if TELEGRAM_PROXY else None


def _load_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text(encoding="utf-8").strip() or 0)
    except Exception:
        return 0


def _save_offset(off: int):
    try:
        OFFSET_FILE.write_text(str(off), encoding="utf-8")
    except Exception as e:
        print(f"[warn] offset 写入失败: {e}")


def _load_pending() -> list:
    if not PENDING_FILE.exists():
        return []
    try:
        df = pd.read_csv(PENDING_FILE, encoding="utf-8-sig",
                         dtype={"id": int, "stock": str, "status": str})
        return df.to_dict("records")
    except Exception as e:
        print(f"[warn] pending 读取失败: {e}")
        return []


def _save_pending(rows: list):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    cols = ["id", "target_date", "side", "stock", "qty_type", "qty", "status"]
    pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows]
                 ).to_csv(PENDING_FILE, index=False, encoding="utf-8-sig")


def _append_order(side: str, stock: str, qty_type: str, qty: float) -> int:
    rows = _load_pending()
    oid = max([r["id"] for r in rows], default=0) + 1
    rows.append({"id": oid, "target_date": dt.date.today().isoformat(),
                 "side": side, "stock": stock, "qty_type": qty_type,
                 "qty": qty, "status": "pending"})
    _save_pending(rows)
    return oid


def _handle(text: str) -> str:
    """解析并处理一条命令，返回回执文本。"""
    m = CMD_RE["help"].match(text)
    if m:
        return ("NewsPulse 远程指令：\n"
                "/buy 600519 5000  ← 次日开盘买入 5000 元\n"
                "/buy 600519 100股 ← 买入 100 股\n"
                "/sell 600519 [500] ← 次日开盘卖出（缺省全卖）\n"
                "/status 持仓/现金/待执行\n"
                "/cancel 3 或 /cancel all\n"
                "指令均为模拟盘，次日开盘价成交")
    m = CMD_RE["status"].match(text)
    if m:
        lines = ["NewsPulse 持仓状态："]
        try:
            pf = pd.read_csv(DATA_DIR / "portfolio.csv", encoding="utf-8-sig")
            last = pf.iloc[-1]
            lines.append(f"总资产 {last['total_value']:.2f} · 现金 {last['cash']:.2f}")
            rows = pf[pf["date"] == str(last["date"])]
            pos = [r for r in rows.to_dict("records")
                   if r.get("stock") and float(r.get("shares", 0) or 0) > 0]
            if pos:
                for r in pos:
                    lines.append(f"  {r['stock']} {r['shares']:.0f}股 "
                                 f"成本{r['cost']:.2f} 市值{r['market_value']:.2f}")
            else:
                lines.append("  当前空仓")
        except Exception as e:
            lines.append(f"  持仓读取失败: {e}")
        pend = _load_pending()
        if pend:
            lines.append("待执行指令：")
            for r in pend:
                if r.get("status") == "pending":
                    lines.append(f"  #{r['id']} {r['side']} {r['stock']} "
                                 f"{r['qty']}{'股' if r['qty_type']=='shares' else '元'} "
                                 f"（{r['target_date']}之后首个交易日开盘）")
        return "\n".join(lines)
    m = CMD_RE["cancel"].match(text)
    if m:
        rows = _load_pending()
        pend = [r for r in rows if r.get("status") == "pending"]
        if not pend:
            return "当前没有待执行指令"
        if m.group(1) == "all":
            for r in pend:
                r["status"] = "cancelled"
            _save_pending(rows)
            return f"已取消 {len(pend)} 条待执行指令"
        cid = int(m.group(1))
        hit = [r for r in pend if r["id"] == cid]
        if not hit:
            return f"未找到待执行指令 #{cid}"
        hit[0]["status"] = "cancelled"
        _save_pending(rows)
        return f"已取消指令 #{cid}"
    m = CMD_RE["buy"].match(text)
    if m:
        stock = m.group(1)
        q = m.group(2) or "1000"
        if m.group(3):
            qty_type, qty = "shares", float(q)
        else:
            qty_type, qty = "amount", float(q)
        if qty <= 0:
            return "金额/股数必须为正"
        if qty_type == "amount" and qty > MAX_ORDER_AMOUNT:
            return f"单笔买入金额上限 {MAX_ORDER_AMOUNT:.0f} 元（撮合层另有单票≤30%约束）"
        oid = _append_order("buy", stock, qty_type, qty)
        return (f"买入指令 #{oid} 已登记：{stock} "
                f"{qty:.0f}{'股' if qty_type=='shares' else '元'}，"
                f"次日开盘价模拟成交（可 /cancel {oid} 取消）")
    m = CMD_RE["sell"].match(text)
    if m:
        stock = m.group(1)
        qty = float(m.group(2)) if m.group(2) else 0.0
        oid = _append_order("sell", stock,
                            "shares" if qty > 0 else "all", qty)
        if qty > 0:
            return (f"卖出指令 #{oid} 已登记：{stock} {qty:.0f}股，"
                    f"次日开盘价模拟成交（可 /cancel {oid} 取消）")
        return (f"卖出指令 #{oid} 已登记：{stock} 全卖，"
                f"次日开盘价模拟成交（可 /cancel {oid} 取消）")
    return ("无法识别的指令。发送 /help 查看支持的命令。"
            "仅接受 /buy /sell /status /cancel /help")


def poll_once(long_poll: int = 1) -> int:
    """拉取并处理新消息，返回处理条数。未配置 token / 网络失败 fail-open 返回 0。
    long_poll：getUpdates 长轮询秒数（crontab 短轮询 1s；常驻 daemon 25s）。"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[info] Telegram 未配置，跳过指令轮询")
        return 0
    off = _load_offset()
    try:
        r = requests.get(
            f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"offset": off, "timeout": long_poll, "allowed_updates": ["message"]},
            proxies=_proxy(), timeout=long_poll + 15)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        print(f"[warn] getUpdates 失败: {e}")
        return 0
    n = 0
    for u in updates:
        off = max(off, u.get("update_id", 0) + 1)
        msg = u.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = str(msg.get("text", ""))
        if chat_id != TELEGRAM_CHAT_ID:
            print(f"[warn] 忽略非本人消息: chat={chat_id}", flush=True)
            continue
        if not text.strip():
            continue
        try:
            reply = _handle(text.strip())
            telegram_push.send_text(reply, chat_id=TELEGRAM_CHAT_ID)
            n += 1
        except Exception as e:
            print(f"[warn] 处理消息异常（消息已投递，offset 继续推进）: {e}", flush=True)
    _save_offset(off)
    return n


def daemon():
    """常驻短轮询（systemd 托管）：每秒一轮 getUpdates(timeout=1)。
    代理链路对长挂起连接黑洞（实测 25s 长轮询被 mihomo 挂死），
    短请求可稳定通过；消息延迟 <2s，仍满足"秒级响应"。"""
    print("[ok] daemon 短轮询启动（timeout=1s）", flush=True)
    while True:
        try:
            n = poll_once(long_poll=1)
            if n:
                print(f"[ok] 处理 {n} 条新消息", flush=True)
        except Exception as e:
            print(f"[warn] 轮询异常（1s 后继续）: {e}", flush=True)
        time.sleep(1)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        daemon()
        return 0
    n = poll_once()
    print(f"[ok] 指令轮询完成，处理 {n} 条新消息")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    sys.exit(main())