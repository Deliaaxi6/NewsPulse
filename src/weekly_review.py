"""周复盘：本周 情绪分 vs 上证指数 相关性复盘（Phase 2）。

- 回放当周 news_*.csv → classify+summarize 得到每日情绪分（LLM 缓存幂等，不新增 API 调用）
- 上证指数日涨跌幅（akshare，失败降级跳过相关性）
- 统计：Pearson 相关系数（情绪分 T vs 次日指数 T+1）、方向命中率（|分|>0.3 样本）、样本数
- 输出 reports/weekly_review_{YYYY-WW}.html（暗色主题 + Chart.js 双轴图）并邮件推送
- 数据不足（<3 个配对样本）仅提示不生成（预热期合理行为）

用法：python src/weekly_review.py [--end 2026-08-15]
"""
import json
import sys
import datetime as dt
from pathlib import Path

import pandas as pd
import numpy as np

import akshare as ak

from config import DATA_DIR, REPORTS_DIR
import filter_news
from daily_report import send_report_email
import alert


PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NewsPulse 周复盘 {week}</title>
<script src="../src/assets/chart.umd.js"></script>
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
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;min-height:280px;margin-bottom:14px}
.chart-box h3{margin:0 0 8px;font-size:14px;color:var(--muted);font-weight:600}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;background:var(--card);font-size:13px}
th,td{border:1px solid var(--border);padding:6px 10px;text-align:left}
th{background:#1b222b;color:var(--muted)}
.pos{color:var(--pos)} .neg{color:var(--neg)}
footer{color:var(--muted);font-size:12px;margin-top:24px}
</style></head><body>
<h1>NewsPulse 周复盘</h1>
<div class="sub">{week} · {range_text} · 模拟交易，不构成投资建议</div>
<div class="kpi-row">
  <div class="kpi-card" style="--kpi:#4a9eff"><div class="kpi-label">情绪分-次日指数 Pearson r</div><div class="kpi-value">{r}</div><div class="kpi-note">样本 {n} 个配对</div></div>
  <div class="kpi-card" style="--kpi:#f5b942"><div class="kpi-label">方向命中率（|分|&gt;0.3）</div><div class="kpi-value">{hit_rate}</div><div class="kpi-note">命中 {hit}/{hit_n} 个信号日</div></div>
  <div class="kpi-card" style="--kpi:#9d7bff"><div class="kpi-label">本周情绪均值</div><div class="kpi-value">{score_mean}</div><div class="kpi-note">样本 {days} 个新闻日</div></div>
</div>
<div class="chart-box"><h3>情绪分 vs 次日上证指数涨跌</h3><canvas id="chart-week"></canvas></div>
<h2>逐日明细</h2>
<table><tr><th>日期</th><th>情绪分</th><th>新闻数</th><th>指数当日%</th><th>指数次日%</th></tr>{day_rows}</table>
<footer>NewsPulse demo · 模拟交易，不构成投资建议 · 图表引擎 Chart.js 4.4.7（本地资源 src/assets/）</footer>
<script>
const D = {labels: {labels}, scores: {scores}, nexts: {nexts}};
new Chart(document.getElementById('chart-week'), {type:'bar', data:{labels:D.labels, datasets:[
  {type:'line', label:'情绪分', data:D.scores, borderColor:'#4a9eff', backgroundColor:'rgba(74,158,255,0.12)', fill:true, tension:0.35, pointRadius:3, yAxisID:'y'},
  {type:'bar', label:'次日指数%', data:D.nexts, backgroundColor:D.nexts.map(v=>v>=0?'rgba(231,76,60,0.55)':'rgba(46,204,113,0.55)'), borderRadius:4, yAxisID:'y1'}
]}, options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#8b98a5'}}},scales:{
  x:{ticks:{color:'#8b98a5'},grid:{color:'#222a33'}},
  y:{position:'left',ticks:{color:'#8b98a5'},grid:{color:'#222a33'}},
  y1:{position:'right',ticks:{color:'#8b98a5'},grid:{drawOnChartArea:false}}}}});
</script>
</body></html>"""


def _week_range(end: dt.date) -> tuple:
    """返回 (周一, 周日) 自然周区间。"""
    monday = end - dt.timedelta(days=end.weekday())
    return monday, monday + dt.timedelta(days=6)


def load_daily_sentiment(start: str, end: str) -> list:
    """回放区间内新闻文件 → 每日情绪分（LLM 缓存幂等）。失败日跳过。"""
    rows = []
    for f in sorted(DATA_DIR.glob("news_*.csv")):
        d = f.stem.replace("news_", "")
        if not (start <= d <= end):
            continue
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            df = filter_news.classify(df, d)
            s = filter_news.summarize(df, d)
            rows.append({"date": d, "score": float(s["senti_score"]),
                         "news": int(s["total_news"])})
        except Exception as e:
            print(f"[warn] {d} 复盘数据读取失败: {e}")
    return rows


def load_index_daily(start: str, end: str) -> dict:
    """上证指数日涨跌幅 {date: pct}。akshare 失败返回 {}（相关性降级跳过）。"""
    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty:
            return {}
        out = {}
        prev_close = None
        for _, r in df.iterrows():
            d = str(r["date"])[:10]
            if not (start <= d <= end):
                continue
            close = float(r["close"])
            if prev_close is not None and prev_close > 0:
                out[d] = round((close - prev_close) / prev_close * 100, 3)
            prev_close = close
        return out
    except Exception as e:
        print(f"[warn] 指数数据不可用，相关性跳过: {e}")
        return {}


def stats(senti: list, idx: dict) -> dict:
    """Pearson r（情绪T vs 次日指数T+1）+ 方向命中率（|分|>0.3 样本）。"""
    pairs = []
    for i in range(len(senti) - 1):
        nxt = idx.get(senti[i + 1]["date"])
        if nxt is None:
            continue
        pairs.append({"date": senti[i]["date"], "score": senti[i]["score"],
                      "next_pct": nxt})
    r, hit, hit_n = None, 0, 0
    for p in pairs:
        if abs(p["score"]) > 0.3:
            hit_n += 1
            if (p["score"] > 0 and p["next_pct"] > 0) or \
               (p["score"] < 0 and p["next_pct"] < 0):
                hit += 1
    if len(pairs) >= 3:
        x = np.array([p["score"] for p in pairs])
        y = np.array([p["next_pct"] for p in pairs])
        if x.std() > 0 and y.std() > 0:
            r = float(np.corrcoef(x, y)[0, 1])
    return {"pairs": pairs, "r": r, "hit": hit, "hit_n": hit_n}


def weekly_review(end: dt.date = None) -> Path:
    """生成周复盘 HTML 并邮件推送。返回报告路径（数据不足返回 None）。"""
    end = end or dt.date.today()
    monday, sunday = _week_range(end)
    start_s, end_s = monday.isoformat(), sunday.isoformat()
    week = f"{monday.isoformat()[:4]}-W{end.isocalendar().week:02d}"
    senti = load_daily_sentiment(start_s, end_s)
    if len(senti) < 3:
        print(f"[warn] 周复盘 {week} 仅 {len(senti)} 个新闻日（<3），跳过生成")
        alert.notify("周复盘跳过", f"{week}（{start_s}~{end_s}）仅 {len(senti)} "
                      f"个新闻日（<3），未生成报告，数据积累中")
        return None
    idx = load_index_daily(start_s, end_s)
    st = stats(senti, idx)
    days = len(senti)
    score_mean = sum(x["score"] for x in senti) / days
    r_txt = f"{st['r']:.3f}" if st["r"] is not None else "n/a（指数数据不可用）"
    hit_txt = (f"{st['hit'] / st['hit_n']:.1%}" if st["hit_n"] else "n/a")
    day_rows = ""
    pairs = {p["date"]: p["next_pct"] for p in st["pairs"]}
    for x in senti:
        nxt = pairs.get(x["date"])
        idx_txt = f"{idx.get(x['date'], 0.0):+.2f}%" if idx.get(x["date"]) is not None else "n/a"
        nxt_txt = f"{nxt:+.2f}%" if nxt is not None else "n/a"
        day_rows += (f"<tr><td>{x['date']}</td><td class=\"{'pos' if x['score']>0 else 'neg'}\">"
                     f"{x['score']:+.2f}</td><td>{x['news']}</td><td>{idx_txt}</td>"
                     f"<td>{nxt_txt}</td></tr>")
    chart = {"labels": [x["date"] for x in senti],
             "scores": [x["score"] for x in senti],
             "nexts": [pairs.get(x["date"]) if pairs.get(x["date"]) is not None else 0
                       for x in senti]}
    html = (PAGE.replace("{week}", week)
                .replace("{range_text}", f"{start_s} ~ {end_s}")
                .replace("{r}", r_txt).replace("{n}", str(len(st["pairs"])))
                .replace("{hit_rate}", hit_txt)
                .replace("{hit}", str(st["hit"])).replace("{hit_n}", str(st["hit_n"]))
                .replace("{score_mean}", f"{score_mean:+.2f}").replace("{days}", str(days))
                .replace("{day_rows}", day_rows)
                .replace("{labels}", json.dumps(chart["labels"], ensure_ascii=False))
                .replace("{scores}", json.dumps(chart["scores"]))
                .replace("{nexts}", json.dumps(chart["nexts"])))
    out = REPORTS_DIR / f"weekly_review_{week}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[ok] 周复盘 → {out}（Pearson r={r_txt}，命中 {st['hit']}/{st['hit_n']}）")
    send_report_email(week, out)
    return out


def main():
    args = sys.argv[1:]
    end = dt.date.today()
    if "--end" in args:
        end = dt.date.fromisoformat(args[args.index("--end") + 1])
    weekly_review(end)


if __name__ == "__main__":
    main()
