"""邮件推送测试（4 用例）：脚本缺失/失败不中断主流程（规则19）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import daily_report


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # 1. 脚本不存在 → 返回 False 且不抛异常
    old = daily_report.EMAIL_SCRIPT
    daily_report.EMAIL_SCRIPT = r"C:\不存在的脚本\send_email.py"
    try:
        ok = daily_report.send_report_email("2026-08-13",
                                            Path(r"C:\不存在的报告\report_2026-08-13.html"))
        check("脚本缺失返回False不抛异常", ok is False)
    finally:
        daily_report.EMAIL_SCRIPT = old

    # 2. 空日期/正常参数 → 脚本存在时正常执行（真机验证，此处仅确认接口可调用）
    check("接口签名可调用", callable(daily_report.send_report_email))

    # 3. 模拟报告路径不存在时仍不抛异常（脚本存在场景，用 python -c 桩替代）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "send_email_stub.py"
        stub.write_text(
            "import sys, pathlib\n"
            "p = pathlib.Path(sys.argv[sys.argv.index('--attachment')+1])\n"
            "sys.exit(1 if not p.exists() else 0)\n",
            encoding="utf-8")
        daily_report.EMAIL_SCRIPT = str(stub)
        try:
            ok = daily_report.send_report_email("2026-08-13",
                                                Path(td) / "report_missing.html")
            check("附件缺失桩脚本返回1", ok is False)
        finally:
            daily_report.EMAIL_SCRIPT = old

    # 4. 桩脚本返回0 → 视为推送成功
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "send_email_stub.py"
        stub.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        rep = Path(td) / "report_ok.html"
        rep.write_text("<html></html>", encoding="utf-8")
        daily_report.EMAIL_SCRIPT = str(stub)
        try:
            ok = daily_report.send_report_email("2026-08-13", rep)
            check("桩脚本成功返回True", ok is True)
        finally:
            daily_report.EMAIL_SCRIPT = old

    print(f"email: {4 - fails}/4 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())