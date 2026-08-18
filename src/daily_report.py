"""⑤ HTML 报告：情绪总览/决策/持仓/成交 → reports/report_{date}.html，生成后 Telegram 推送。

图表版 dashboard（2026-08-13 升级）：暗色主题 + KPI 卡片 + Chart.js 3 图
（情绪趋势/新闻量/情绪分布），模板取自 GitHub 开源 KPI_Analyzer_Dashboard 改造；
图表引擎 Chart.js 4.4.7 已本地化到 src/assets/（离线可用，无 CDN 依赖）。
"""
import json
import subprocess
import sys
import datetime as dt
from pathlib import Path

import pandas as pd

from config import (DATA_DIR, REPORTS_DIR,
                    TG_SCRIPT, TG_CONFIG)
import cyq
import select_stock
import telegram_push

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _inline_assets() -> str:
    """把本地 Chart.js 两个文件内联进 HTML（自包含，Telegram 附件在任意设备打开可显示）。
    `</script` 转义防提前闭合；文件缺失 fail-open 返回空。"""
    parts = []
    for name in ("chart.umd.js", "chartjs-plugin-annotation.min.js"):
        p = ASSETS_DIR / name
        if not p.exists():
            print(f"[warn] 图表资源缺失 {p}，图表将不显示（页面其余正常）")
            continue
        try:
            js = p.read_text(encoding="utf-8").replace("</script", "<\\/script")
            parts.append(f"<script>{js}</script>")
        except Exception as e:
            print(f"[warn] 图表资源读取失败 {p}: {e}")
    return "\n".join(parts)

PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NewsPulse 日报 {date}</title>
{chart_scripts}
<style>
:root{--bg:#0f1419;--card:#161b22;--border:#2a3139;--text:#e6edf3;--muted:#8b98a5;--accent:#4a9eff;--pos:#e74c3c;--neg:#2ecc71}
*{box-sizing:border-box}
body{font-family:'Microsoft YaHei','Segoe UI',sans-serif;background:var(--bg);color:var(--text);max-width:1100px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;color:var(--accent);margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
h2{font-size:16px;color:#7fb2e5;border-bottom:1px solid var(--border);padding-bottom:4px;margin:22px 0 6px}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:18px}
.kpi-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;position:relative;overflow:hidden}
.kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--kpi,#4a9eff),transparent)}
.kpi-label{color:var(--muted);font-size:12px}
.kpi-value{font-size:26px;font-weight:700;margin-top:4px}
.kpi-note{color:var(--muted);font-size:11px;margin-top:2px}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-bottom:6px}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;height:320px;display:flex;flex-direction:column}
.chart-box h3{margin:0 0 8px;font-size:14px;color:var(--muted);font-weight:600}
.chart-box canvas{flex:1;min-height:0;width:100%}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;background:var(--card);font-size:13px}
th,td{border:1px solid var(--border);padding:6px 10px;text-align:left}
th{background:#1b222b;color:var(--muted)}
.pos{color:var(--pos)} .neg{color:var(--neg)} .hold{color:var(--muted)}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-size:12px}
.b-bull{background:var(--pos)} .b-bear{background:var(--neg)} .b-hold{background:#6c7a89}
footer{color:var(--muted);font-size:12px;margin-top:24px}
</style></head><body>
<h1>NewsPulse 日报</h1>
<div class="sub">{date} · {verdict} · 模拟交易，不构成投资建议</div>
{bearish_banner}
<div class="kpi-row">
  <div class="kpi-card" style="--kpi:{score_color}"><div class="kpi-label">市场情绪分</div><div class="kpi-value">{score}</div><div class="kpi-note">利好 {pos} · 利空 {neg} · 中性 {neu}</div></div>
  <div class="kpi-card" style="--kpi:#4a9eff"><div class="kpi-label">今日新闻</div><div class="kpi-value">{total}</div><div class="kpi-note">来源：东财快讯</div></div>
  <div class="kpi-card" style="--kpi:#f5b942"><div class="kpi-label">总资产</div><div class="kpi-value">{assets}</div><div class="kpi-note">模拟账户 · 10万初始</div></div>
  <div class="kpi-card" style="--kpi:#9d7bff"><div class="kpi-label">今日决策</div><div class="kpi-value">{decision_count}</div><div class="kpi-note">信号股数</div></div>
</div>
<div class="chart-grid">
  <div class="chart-box"><h3>情绪分趋势</h3><canvas id="chart-trend"></canvas></div>
  <div class="chart-box"><h3>每日新闻量</h3><canvas id="chart-news"></canvas></div>
  <div class="chart-box"><h3>情绪分布</h3><canvas id="chart-dist"></canvas></div>
</div>
<h2>今日决策</h2>
<table><tr><th>股票</th><th>信号</th><th>杠杆</th><th>原因</th></tr>{decision_rows}</table>
<h2>策略预测准确率（近20条）</h2>
<table><tr><th>预测日</th><th>股票</th><th>预测方向</th><th>实际涨跌</th><th>结果</th></tr>{prediction_rows}</table>
<h2>持仓快照</h2>
<table><tr><th>股票</th><th>持股</th><th>成本价</th><th>市值</th><th>现金</th><th>总资产</th></tr>{position_rows}</table>
<h2>筹码分布（CYQ）</h2>
<table><tr><th>股票</th><th>获利盘</th><th>平均成本</th><th>集中度</th><th>现价</th><th>摘要</th></tr>{cyq_rows}</table>
<h2>成交记录</h2>
<table><tr><th>日期</th><th>股票</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>原因</th></tr>{trade_rows}</table>
<footer>NewsPulse demo · 模拟交易，不构成投资建议 · 图表引擎 Chart.js 4.4.7（本地资源 src/assets/）</footer>
<script>
const CHART_DATA = __CHART_JSON__;
function darkOpts(){return{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#8b98a5'}}},scales:{x:{ticks:{color:'#8b98a5'},grid:{color:'#222a33'}},y:{ticks:{color:'#8b98a5'},grid:{color:'#222a33'}}}}}
if (CHART_DATA.labels.length && CHART_DATA.scores.length) {
  const maAnno = CHART_DATA.scores.length >= 7 ? {ma7:{type:'line',scaleID:'y',value:CHART_DATA.ma7,borderColor:'#f5b942',borderDash:[4,4],borderWidth:1,label:{content:'7日均',display:true,color:'#f5b942'}}} : {};
  new Chart(document.getElementById('chart-trend'), {
      type: 'line',
      data: {labels: CHART_DATA.labels, datasets: [{label: '情绪分', data: CHART_DATA.scores, borderColor: '#4a9eff', backgroundColor: 'rgba(74,158,255,0.12)', fill: true, tension: 0.35, pointRadius: 3, pointBackgroundColor: '#4a9eff'}]},
      options: Object.assign(darkOpts(), {plugins: {legend: {display: false}, annotation: {annotations: maAnno}}})
    });
  new Chart(document.getElementById('chart-news'),{type:'bar',data:{labels:CHART_DATA.labels,datasets:[{label:'新闻数',data:CHART_DATA.news,backgroundColor:'#3b6ea5',borderRadius:4}]},options:darkOpts()});
  new Chart(document.getElementById('chart-dist'),{type:'doughnut',data:{labels:['利好','利空','中性'],datasets:[{data:[CHART_DATA.dist.pos,CHART_DATA.dist.neg,CHART_DATA.dist.neu],backgroundColor:['#e74c3c','#2ecc71','#8b98a5'],borderColor:'#161b22'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#8b98a5'}}}}});
} else {
  document.querySelectorAll('canvas').forEach(function(c){c.outerHTML='<div style="color:#8b98a5;font-size:13px">暂无历史数据，明日生成图表</div>'});
}
</script>
</body></html>"""


def verdict(score):
    if score >= 0.3:
        return "情绪偏多，系统考虑加仓"
    if score <= -0.3:
        return "情绪偏空，系统倾向减仓"
    return "情绪中性，观望为主"


def _bearish_banner(score: float, pos, neg) -> str:
    """利空主导横幅 HTML（情绪分 ≤ BEARISH_SCORE 时非空）。"""
    if score > telegram_push.BEARISH_SCORE:
        return ""
    return (f"<div style='background:#3a1d1d;border:1px solid #7a2d2d;color:#ff8b8b;"
            f"padding:10px 14px;border-radius:8px;margin:0 0 14px;font-weight:600'>"
            f"⚠️ 今日利空主导（情绪分 {score:+.2f}，利空 {neg} / "
            f"利好 {pos}），注意持仓风险</div>")


def score_color(score):
    """A股习惯：看多红、看空绿、中性蓝。"""
    if score >= 0.3:
        return "#e74c3c"
    if score <= -0.3:
        return "#2ecc71"
    return "#4a9eff"


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
        return "<tr><td colspan='5' style='color:#8b98a5'>尚无校验数据（明日开始累计）</td></tr>"
    df = pd.read_csv(p, encoding="utf-8-sig", dtype={"stock": str})
    df = df.tail(20)
    rows = ""
    for r in df.to_dict("records"):
        ok = "✓" if r["hit"] == 1 else "✗"
        rows += (f"<tr><td>{r['pred_date']}</td><td>{r['stock']}</td>"
                 f"<td>{r['predict']}</td><td>{r['actual_pct']:+.2f}%</td>"
                 f"<td>{ok}</td></tr>")
    return rows


def chart_data(senti: pd.DataFrame) -> dict:
    """情绪历史 → 图表数据（日期/情绪分/新闻量/当日分布；≥7 天加 7 日均线）。

    同日多条运行记录按天去重（取当日最后一条），避免趋势图出现重复点。
    """
    senti = senti.drop_duplicates("date", keep="last")
    labels = [str(d)[5:] for d in senti["date"]]
    scores = [float(x) for x in senti["senti_score"]]
    news = [int(x) for x in senti["total_news"]]
    last = senti.iloc[-1]
    out = {"labels": labels, "scores": scores, "news": news,
           "dist": {"pos": int(last["pos_cnt"]), "neg": int(last["neg_cnt"]),
                    "neu": int(last["neutral_cnt"])}}
    if len(scores) >= 7:
        out["ma7"] = round(sum(scores[-7:]) / 7, 3)
    return out


def _fill(tpl: str, **kw) -> str:
    for k, v in kw.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


SENT_MARK_FILE = DATA_DIR / "report_sent.log"


def _report_hash(date_str, report_path: Path) -> str:
    """同日报告内容指纹：md5(日期 + 文件内容)。内容相同→跳过重发；内容变化（如新增数据）→重发。
    文件读写失败 fail-open 返回空串。"""
    try:
        import hashlib
        h = hashlib.md5()
        h.update(date_str.encode("utf-8"))
        h.update(report_path.read_bytes())
        return h.hexdigest()
    except Exception:
        return ""


def _already_sent(date_str, report_path: Path) -> bool:
    """同日同内容已推送过 → 跳过重发（内容级去重，防重复运行重复推送）。"""
    h = _report_hash(date_str, report_path)
    if not h:
        return False
    try:
        if not SENT_MARK_FILE.exists():
            return False
        for line in SENT_MARK_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip() == h:
                return True
    except Exception as e:
        print(f"[warn] 推送标记读取失败（fail-open 照常推送）: {e}")
    return False


def _mark_sent(date_str, report_path: Path) -> None:
    h = _report_hash(date_str, report_path)
    if not h:
        return
    try:
        with SENT_MARK_FILE.open("a", encoding="utf-8") as f:
            f.write(h + "\n")
    except Exception as e:
        print(f"[warn] 推送标记写入失败（不影响推送结果）: {e}")


def send_report_tg(date_str, report_path: Path) -> bool:
    """报告生成后推送 Telegram（复用 send_telegram.py）。失败仅告警，不中断主流程。
    降噪：同日同内容已推送 → 跳过；标记读写失败 fail-open 照常推送。"""
    if _already_sent(date_str, report_path):
        print(f"[info] {date_str} 报告已推送过（内容指纹一致），跳过重复推送")
        return True
    script = Path(TG_SCRIPT)
    if not script.exists():
        print(f"[warn] 推送脚本不存在 {script}，跳过推送（本地开发可忽略）")
        return False
    cmd = [sys.executable, str(script),
           "--event", "idle",
           "--project", "NewsPulse",
           "--message", f"NewsPulse 日报 {date_str} 已生成，请查收附件",
           "--attachment", str(report_path),
           "--foreground"]
    if TG_CONFIG:
        cmd += ["--config", TG_CONFIG]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if r.returncode == 0:
            print("[ok] 日报已推送")
            _mark_sent(date_str, report_path)
            return True
        print(f"[warn] 推送失败: {r.stderr.strip()[:200]}")
    except Exception as e:
        print(f"[warn] 推送异常: {e}")
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

    pool = select_stock.load_pool(date_str)
    names = {r["symbol"]: r["name"] for r in pool}
    d_rows = "".join(
        f"<tr><td>{names.get(r['stock'], r['stock'])}</td>"
        f"<td class='{r['signal']}'><span class='badge b-{r['signal']}'>{r['signal']}</span></td>"
        f"<td>{r['leverage']}倍</td><td>{r['reason']}</td></tr>" for r in decisions) or \
        "<tr><td colspan='4' style='color:#8b98a5'>今日无信号，观望</td></tr>"
    p_rows = "".join(
        f"<tr><td>{names.get(r['stock'], r['stock'])}</td><td>{r['shares']:.0f}</td>"
        f"<td>{r['cost']:.2f}</td><td>{r['market_value']:.2f}</td>"
        f"<td>{r['cash']:.2f}</td><td><b>{r['total_value']:.2f}</b></td></tr>" for r in positions) or \
        "<tr><td colspan='6' style='color:#8b98a5'>当前空仓</td></tr>"
    t_rows = "".join(
        f"<tr><td>{r['date']}</td><td>{names.get(r['stock'], r['stock'])}</td>"
        f"<td class='{'pos' if r['action']=='buy' else 'neg'}'>{r['action']}</td>"
        f"<td>{r['price']:.2f}</td><td>{r['shares']:.0f}</td><td>{r['amount']:.2f}</td>"
        f"<td>{r['reason']}</td></tr>" for r in trades) or \
        "<tr><td colspan='7' style='color:#8b98a5'>暂无成交</td></tr>"

    def cyq_cell(sym, name):
        try:
            res = cyq.cyq(cyq.fetch_daily(sym))
        except Exception as e:
            print(f"[warn] {sym} 筹码分布失败: {e}")
            res = None
        if res is None:
            return (f"<tr><td>{name}</td><td colspan='5' style='color:#8b98a5'>"
                    f"{cyq.summarize(res)}</td></tr>")
        return (f"<tr><td>{name}</td><td>{res['winner']:.0%}</td>"
                f"<td>{res['avg_cost']:.2f}</td><td>{res['concentration']:.1%}</td>"
                f"<td>{res['last_close']:.2f}</td><td>{cyq.summarize(res)}</td></tr>")

    c_rows = "".join(cyq_cell(r["symbol"], r["name"]) for r in pool) or \
        "<tr><td colspan='6' style='color:#8b98a5'>今日观察池为空，无筹码分布</td></tr>"

    assets = positions[-1]["total_value"] if positions else 100000.0
    bearish_banner = _bearish_banner(score, last["pos_cnt"], last["neg_cnt"])
    html = (_fill(PAGE, date=date_str, score=f"{score:+.2f}", total=last["total_news"],
                  pos=last["pos_cnt"], neg=last["neg_cnt"], neu=last["neutral_cnt"],
                  verdict=verdict(score), score_color=score_color(score),
                  bearish_banner=bearish_banner,
                  assets=f"{assets:,.0f}", decision_count=len(decisions),
                  decision_rows=d_rows, prediction_rows=prediction_rows_html(),
                  position_rows=p_rows, trade_rows=t_rows, cyq_rows=c_rows,
                  chart_scripts=_inline_assets())
            .replace("__CHART_JSON__", json.dumps(chart_data(senti), ensure_ascii=False)))
    out = REPORTS_DIR / f"report_{date_str}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[ok] 报告 → {out}")
    send_report_tg(date_str, out)
    buys = [{"stock": names.get(r["stock"], r["stock"]), "leverage": r["leverage"],
             "reason": r["reason"]} for r in decisions if r.get("signal") == "buy"]
    telegram_push.send_text(
        telegram_push.report_summary(date_str, score, int(last["total_news"]),
                                     int(last["pos_cnt"]), int(last["neg_cnt"]),
                                     assets, len(decisions), buys))
    telegram_push.send_to_channel(
        telegram_push.report_summary(date_str, score, int(last["total_news"]),
                                     int(last["pos_cnt"]), int(last["neg_cnt"]),
                                     assets, len(decisions), buys))


if __name__ == "__main__":
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    main(date_str)
