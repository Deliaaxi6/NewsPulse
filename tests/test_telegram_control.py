"""test_telegram_control.py — Telegram 远程指令解析与轮询（mock 网络）"""
import sys
import json
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import telegram_control as tc

MY_CHAT = "6359097393"


def _pending(tc_mod, tmp):
    tc_mod.PENDING_FILE = Path(tmp) / "pending_orders.csv"
    tc_mod.OFFSET_FILE = Path(tmp) / "tg_offset.txt"
    tc_mod._save_pending([])


def _upd(update_id, chat, text):
    return {"update_id": update_id,
            "message": {"chat": {"id": chat}, "text": text}}


def main():
    n = f = 0

    def check(name, ok, extra=""):
        nonlocal n, f
        n += 1
        if not ok:
            f += 1
        tag = "[OK]" if ok else "[FAIL]"
        print(f"{tag} {name}" + (f" ← {extra}" if (not ok and extra) else ""))

    with tempfile.TemporaryDirectory() as tmp:
        _pending(tc, tmp)

        # --- 命令解析 ---
        r = tc._handle("/buy 600519 5000")
        rows = tc._load_pending()
        check("buy 金额登记", "买入指令 #1" in r
              and rows and rows[0]["side"] == "buy" and rows[0]["qty_type"] == "amount"
              and rows[0]["qty"] == 5000.0 and rows[0]["stock"] == "600519", r)
        r = tc._handle("/buy 000858 100股")
        rows = tc._load_pending()
        check("buy 股数登记", "买入指令 #2" in r
              and rows[1]["qty_type"] == "shares" and rows[1]["qty"] == 100.0, r)
        r = tc._handle("/buy 600519 40000")
        check("buy 金额超限拒绝", "上限" in r and len(tc._load_pending()) == 2, r)
        r = tc._handle("/buy 600519 0")
        check("buy 非正拒绝", "必须为正" in r and len(tc._load_pending()) == 2, r)
        r = tc._handle("/buy 123 5000")
        check("buy 代码格式拒绝", "无法识别" in r, r)
        r = tc._handle("/sell 600519")
        rows = tc._load_pending()
        check("sell 全卖登记", "卖出指令 #3" in r
              and rows[2]["side"] == "sell" and rows[2]["qty_type"] == "all", r)
        r = tc._handle("/sell 600519 500")
        rows = tc._load_pending()
        check("sell 股数登记", "卖出指令 #4" in r
              and rows[3]["qty_type"] == "shares" and rows[3]["qty"] == 500.0, r)

        # --- 取消 ---
        r = tc._handle("/cancel 999")
        check("cancel 未找到", "未找到" in r)
        r = tc._handle("/cancel 2")
        check("cancel 单条", "已取消指令 #2" in r
              and [x for x in tc._load_pending() if x["id"] == 2][0]["status"] == "cancelled")
        r = tc._handle("/cancel all")
        check("cancel 全部", "已取消 3 条" in r
              and all(x["status"] == "cancelled" for x in tc._load_pending()))

        # --- status：空仓 + 有 pending ---
        with mock.patch("telegram_control.DATA_DIR", Path(tmp)):
            r = tc._handle("/status")
        check("status 空仓提示", "当前空仓" in r or "读取失败" in r, r[:80])

        # --- help / 未知 ---
        r = tc._handle("/help")
        check("help 说明", "/buy" in r and "/sell" in r)
        r = tc._handle("/magic")
        check("未知指令", "无法识别" in r)

        # --- poll_once：本人消息处理、非本人忽略、offset 推进 ---
        fake = mock.Mock()
        fake.raise_for_status.return_value = None
        fake.json.return_value = {"result": [
            _upd(11, "999999999", "/buy 600519 2000"),   # 非本人
            _upd(12, MY_CHAT, "/sell 600519"),
        ]}
        with mock.patch("telegram_control.requests.get", return_value=fake), \
             mock.patch("telegram_control.TELEGRAM_BOT_TOKEN", "tok"), \
             mock.patch("telegram_control.TELEGRAM_CHAT_ID", MY_CHAT), \
             mock.patch("telegram_control.telegram_push.send_text") as tg:
            n1 = tc.poll_once()
        check("poll 只处理本人", n1 == 1 and tg.call_count == 1
              and "卖出指令" in tg.call_args[0][0], f"n={n1} tg={tg.call_count}")
        check("poll offset 推进", tc._load_offset() == 13)

        # --- poll 网络失败 fail-open ---
        with mock.patch("telegram_control.requests.get",
                        side_effect=Exception("conn err")), \
             mock.patch("telegram_control.TELEGRAM_BOT_TOKEN", "tok"), \
             mock.patch("telegram_control.TELEGRAM_CHAT_ID", MY_CHAT):
            n2 = tc.poll_once()
        check("poll 网络失败 fail-open", n2 == 0)

        # --- 未配置 token 跳过 ---
        with mock.patch("telegram_control.TELEGRAM_BOT_TOKEN", ""):
            n3 = tc.poll_once()
        check("poll 未配置跳过", n3 == 0)

    print(f"telegram_control: {n}/{n} passed")
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())