"""⑤ HTML 报告：情绪总览/决策/持仓/成交 → reports/report_{date}.html，生成后邮件推送。"""
import subprocess
import sys
import datetime as dt
from pathlib import Path

import pandas as pd

from config import (DATA_DIR, REPORTS_DIR, STOCKS,
                    EMAIL_SCRIPT, EMAIL_CONFIG, EMAIL_TO, EMAIL_CC)

PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>NewsPulse 日报 {date}</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:960px;margin:20px auto;padding:0 16px;background:#fafafa}}
h1{{color:#1a3a5c}} h2{{color:#2c5f8a;border-bottom:2px solid #dde6ee;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;margin:10px 0;background:#fff}}
th,td{{border:1px solid #dde6ee;padding:6px 10px;text-align:left;font-size:14px}}
th{{background:#eef4f9}}
.pos{{color:#c0392b}} .neg{{color:#27ae60}}
.bull{{color:#c0392b}} .bear{{color:#27ae60}} .hold{{color:#7f8c8d}}
.badge{{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-size:12px}}
.b-bull{{background:#c0392b}} .b-bear{{background:#27ae60}} .b-hold{{background:#7f8c8d}}
</style></head><body>
<h1>NewsPulse 日报 — {date}</h1>
<h2>市场情绪</h2>
<table><tr><th>情绪分</th><th>新闻总数</th><th>利好</th><th>利空</th><th>中性</th><th>解读</th></tr>
<tr><td><b>{score}</b></td><td>{total}</td><td class="pos">{pos}</td><td class="neg">{neg}</td><td>{neu}</td><td>{verdict}</td></tr></table>
<h2>今日决策</h2>
<table><tr><th>股票</th><th>信号</th><th>杠杆</th><th>原因</th></tr>{decision_rows}</table>
<h2>策略预测准确率（近20条）</h2>
<table><tr><th>预测日</th><th>股票</th><th>预测方向</th><th>实际涨跌</th><th>结果</th></tr>{prediction_rows}</table>
<h2>持仓快照</h2>
<table><tr><th>股票</th><th>持股</th><th>成本价</th><th>市值</th><th>现金</th><th>总资产</th></tr>{position_rows}</table>
<h2>成交记录</h2>
<table><tr><th>日期</th><th>股票</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>原因</th></tr>{trade_rows}</table>
<p style="color:#999;font-size:12px">NewsPulse demo · 模拟交易，不构成投资建议</p>
</body></html>"""


def verdict(score):
    if score >= 0.3:
        return "情绪偏多，系统考虑加仓"
    if score <= -0.3:
        return "情绪偏空，系统倾向减仓"
    return "情绪中性，观望为主"


def load_optional(name, date_str):
    p = DATA_DIR / name
    if p.exists():
        try:
            return pd.read_csv(p, encoding="utf-8-sig", dtype={"stock": str}).to_dict("records")
        except Exception:
            return []
    if (DATA_DIR / f"decision_{date_str}.csv").exists() and name == f"decision_{date_str}.csv":
        return pd.read_csv(DATA_DIR / f"decision_{date_str}.csv", encoding="utf-8-sig", dtype={"stock": str}).to_dict("records")
    return []


def prediction_rows_html():
    p = DATA_DIR / "predictions.csv"
    if not p.exists():
        return "<tr><td colspan='5' style='color:#999'>尚无校验数据（明日开始累计）</td></tr>"
    df = pd.read_csv(p, encoding="utf-8-sig", dtype={"stock": str})
    df = df.tail(20)
    rows = ""
    for r in df.to_dict("records"):
        ok = "✓" if r["hit"] == 1 else "✗"
        rows += (f"<tr><td>{r['pred_date']}</td><td>{r['stock']}</td>"
                 f"<td>{r['predict']}</td><td>{r['actual_pct']:+.2f}%</td>"
                 f"<td>{ok}</td></tr>")
    return rows


def send_report_email(date_str, report_path: Path) -> bool:
    """报告生成后推送邮件（复用 send_email.py）。失败仅告警，不中断主流程。"""
    script = Path(EMAIL_SCRIPT)
    if not script.exists():
        print(f"[warn] 邮件脚本不存在 {script}，跳过推送（本地开发可忽略）")
        return False
    cmd = [sys.executable, str(script),
           "--to", EMAIL_TO, "--cc", EMAIL_CC,
           "--event", "idle",
           "--project", "NewsPulse",
           "--message", f"NewsPulse 日报 {date_str} 已生成，请查收附件",
           "--subject", f"NewsPulse 日报 {date_str}",
           "--attachment", str(report_path),
           "--foreground"]
    if EMAIL_CONFIG:
        cmd += ["--config", EMAIL_CONFIG]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            print("[ok] 日报邮件已推送")
            return True
        print(f"[warn] 邮件推送失败: {r.stderr.strip()[:200]}")
    except Exception as e:
        print(f"[warn] 邮件推送异常: {e}")
    return False


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    senti = pd.read_csv(DATA_DIR / "daily_sentiment.csv", encoding="utf-8-sig")
    last = senti.iloc[-1]
    score = float(last["senti_score"])

    decisions = load_optional(f"decision_{date_str}.csv", date_str)
    positions = load_optional("portfolio.csv", date_str)
    trades = load_optional("trade_log.csv", date_str)
    if positions:
        positions = [r for r in positions if r["date"] == date_str]
    if trades:
        trades = [r for r in trades if r["date"] == date_str]

    names = {s["symbol"]: s["name"] for s in STOCKS}
    d_rows = "".join(
        f"<tr><td>{names.get(r['stock'], r['stock'])}</td>"
        f"<td class='{r['signal']}'><span class='badge b-{r['signal']}'>{r['signal']}</span></td>"
        f"<td>{r['leverage']}倍</td><td>{r['reason']}</td></tr>" for r in decisions)
    p_rows = "".join(
        f"<tr><td>{names.get(r['stock'], r['stock'])}</td><td>{r['shares']:.0f}</td>"
        f"<td>{r['cost']:.2f}</td><td>{r['market_value']:.2f}</td>"
        f"<td>{r['cash']:.2f}</td><td><b>{r['total_value']:.2f}</b></td></tr>" for r in positions) or \
        "<tr><td colspan='6' style='color:#999'>当前空仓</td></tr>"
    t_rows = "".join(
        f"<tr><td>{r['date']}</td><td>{names.get(r['stock'], r['stock'])}</td>"
        f"<td class='{'pos' if r['action']=='buy' else 'neg'}'>{r['action']}</td>"
        f"<td>{r['price']:.2f}</td><td>{r['shares']:.0f}</td><td>{r['amount']:.2f}</td>"
        f"<td>{r['reason']}</td></tr>" for r in trades) or \
        "<tr><td colspan='7' style='color:#999'>暂无成交</td></tr>"

    html = PAGE.format(date=date_str, score=score, total=last["total_news"],
                       pos=last["pos_cnt"], neg=last["neg_cnt"], neu=last["neutral_cnt"],
                       verdict=verdict(score), decision_rows=d_rows,
                       prediction_rows=prediction_rows_html(),
                       position_rows=p_rows, trade_rows=t_rows)
    out = REPORTS_DIR / f"report_{date_str}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[ok] 报告 → {out}")
    send_report_email(date_str, out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)