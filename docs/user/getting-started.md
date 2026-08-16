# Getting Started — 快速上手

> 面向使用者（你本人）。本系统每天自动跑，你只需读 Telegram 报告。

## 我每天需要做什么？

**什么都不用做**（系统 16:30 自动运行）。你每天会收到一条 Telegram 消息，内容包括：
- 当日市场情绪（利好/利空/中性 + 分数）
- 系统今日的操作（买入/卖出/观望 + 原因）
- 当前持仓与收益
- 杠杆档位与风险提示

## 我想看更多细节？

报告 HTML 附带关键数据。完整数据在 `data/` 目录的 CSV 文件里：
- `data/daily_sentiment.csv` — 每天情绪分数历史
- `data/trade_log.csv` — 每笔模拟成交记录
- `data/portfolio.csv` — 每日持仓快照

## 我想手动触发一次运行？

```bash
# Linux 服务器上
cd /opt/newsquant
bash run_all.sh
```

或只跑某个模块（带日期）：
```bash
python src/fetch_news.py --date 2026-08-10
```

## 系统出了状况我会知道吗？

会。三类通知：
1. **日常报告**：每天 16:30 后（工作日）
2. **熔断警告**：触发爆仓熔断时（红色醒目标题）
3. **异常通知**：数据源失效/脚本崩溃/熔断后冷却期翻倍时

如果当天没收到 Telegram 消息且非节假日，先看：
```bash
cd /opt/newsquant && tail -50 logs/run_YYYY-MM-DD.log
```
（报告问题时可把日志尾部发给 AI 协作者）

## 我想暂停系统？

```bash
crontab -e
# 注释掉 NewsPulse 那一行（行首加 #）保存即可
```

## 本机（Windows）环境

本机用于开发测试：Python 3.13（Miniconda）。安装依赖：
```bash
pip install -r requirements.txt
```
本地运行不需要 secrets.json（跳过推送即可测试全流程）。