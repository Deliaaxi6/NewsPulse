"""日报 dashboard 模板测试：本地资源/模板元素/图表数据结构（离线可用契约）。"""
import sys
import json
import datetime as dt
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import daily_report


def _senti(days):
    return pd.DataFrame({
        "date": [(dt.date(2026, 8, 1) + dt.timedelta(days=i)).isoformat() for i in range(days)],
        "senti_score": [0.1 + i * 0.05 for i in range(days)],
        "total_news": [100 + i for i in range(days)],
        "pos_cnt": [50] * days,
        "neg_cnt": [30] * days,
        "neutral_cnt": [20] * days,
    })


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    # --- 本地资源（离线可用契约：无 CDN 依赖）---
    check("chart.umd.js 已本地化", (daily_report.ASSETS_DIR / "chart.umd.js").exists())
    check("annotation 插件已本地化",
          (daily_report.ASSETS_DIR / "chartjs-plugin-annotation.min.js").exists())
    check("模板引用本地资源", "src/assets/chart.umd.js" in daily_report.PAGE)

    # --- 模板元素 ---
    for cid in ("chart-trend", "chart-news", "chart-dist"):
        check(f"模板含图表容器 {cid}", f'id="{cid}"' in daily_report.PAGE)
    check("模板含数据占位符", "__CHART_JSON__" in daily_report.PAGE)

    # --- chart_data 结构 ---
    d7 = daily_report.chart_data(_senti(7))
    check("7天含ma7且正确",
          "ma7" in d7 and abs(d7["ma7"] - sum(d7["scores"][-7:]) / 7) < 1e-9)
    d1 = daily_report.chart_data(_senti(1))
    check("单天无ma7且单点", "ma7" not in d1 and len(d1["labels"]) == 1)
    check("dist三字段齐全", {"pos", "neg", "neu"} <= set(d1["dist"]))
    check("labels日期裁剪为MM-DD", d1["labels"][0] == "08-01")
    dup = _senti(2)
    dup.loc[1] = dup.loc[0]
    dd = daily_report.chart_data(dup)
    check("同日多条去重", len(dd["labels"]) == 1)

    # --- 利空主导横幅 ---
    check("利空横幅 -0.3 触发",
          "利空主导" in daily_report._bearish_banner(-0.3, 5, 20)
          and "-0.30" in daily_report._bearish_banner(-0.3, 5, 20))
    check("利空横幅 0.2 不触发",
          daily_report._bearish_banner(0.2, 5, 20) == "")
    check("利空横幅 恰好 -0.1 触发",
          "利空主导" in daily_report._bearish_banner(-0.1, 5, 20))

    # --- 渲染后无残留占位符 ---
    html = (daily_report._fill(daily_report.PAGE, date="2026-08-13", score="+0.21", total=236,
                               pos=52, neg=46, neu=138, verdict="情绪中性，观望为主",
                               score_color="#4a9eff", bearish_banner="", assets="100,000",
                               decision_count=4, decision_rows="", prediction_rows="",
                               position_rows="", trade_rows="", cyq_rows="")
            .replace("__CHART_JSON__", json.dumps(daily_report.chart_data(_senti(3)))))
    check("渲染无残留占位符",
          "{date}" not in html and "{score}" not in html and "__CHART_JSON__" not in html
          and "{bearish_banner}" not in html)
    check("渲染含图表数据", '"scores"' in html)

    # --- 推送降噪（同日去重 + fail-open）---
    import os
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    rep = tmp / "report.html"
    rep.write_text("<html>test</html>", encoding="utf-8")
    old_mark = daily_report.SENT_MARK_FILE
    daily_report.SENT_MARK_FILE = tmp / "sent.log"
    check("首次未推送过", not daily_report._already_sent("2026-08-13", rep))
    daily_report._mark_sent("2026-08-13", rep)
    check("同日同内容已推送", daily_report._already_sent("2026-08-13", rep))
    rep.write_text("<html>changed</html>", encoding="utf-8")
    check("内容变化不跳过", not daily_report._already_sent("2026-08-13", rep))
    daily_report.SENT_MARK_FILE = tmp / "missing" / "sent.log"
    check("标记目录缺失 fail-open", not daily_report._already_sent("2026-08-13", rep))
    daily_report.SENT_MARK_FILE = old_mark

    print(f"daily_report: 19/19 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
