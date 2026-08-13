# NewsPulse — ROADMAP

> 项目名称：NewsPulse（新闻情绪驱动的全自动学习型量化模拟交易系统）
> 文档版本：1.0 | 设计日期：2026-08-10
> 设计方式：spec-skill 完整流程（绿色项目）

## Vision

**一句话愿景**：每日新闻情绪驱动的全自动学习型量化模拟交易系统。

**受众**：仅自己（学生，Python 新手，正在系统性学习量化交易与自动化编程）。
**核心信念**：通过真实数据管道（新闻→情绪→决策→成交→复盘）闭环，学习量化全链路，而不是追求模拟盘盈利。

## 硬约束（不可更改）

1. 资金：实盘资金 100 元不动，模拟资金 10 万
2. 合规：不进行真实交易、不推荐他人投资、境内合规红线（不碰外汇/二元期权）
3. 预算：本项目边际成本 ¥0/月（火山云服务器为已有订阅，不计入）
4. 部署：火山云 Linux 服务器（1核2G），crontab 调度
5. 语言：Python 3.10+（服务器）/ 3.13（本地测试）
6. 数据源：国内新闻优先（东财/新浪/财联社），Telegram 暂缓
7. 筛选：关键词规则筛选（阶段1），大模型升级留待阶段3
8. 决策：情绪分 + 行情趋势 → 买卖信号 + 杠杆档位（1/2/3倍）
9. 告警：复用现有邮件脚本 send_email.py

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.10+ | 金融数据生态最强、社区教程多、AI辅助友好 |
| 数据 | akshare | 内置东财/新浪新闻接口，一次调用拿数据，免费 |
| 处理 | pandas | CSV 存储与中文数据处理成熟 |
| 存储 | 纯 CSV 目录 | 人眼可读、适合学习数据流向 |
| 调度 | crontab | Linux 标准定时方案 |
| 报告 | HTML 模板生成静态文件 | 零安全面、零维护 |
| 通知 | 现有 send_email.py | 复用已验证脚本 |

## 架构概览

```
[每日 16:30 crontab 触发 (工作日)]
┌──────────────────────────────────────────────┐
│  ① fetch_news.py   拉东财快讯+4只个股新闻     │
│       → data/news_YYYYMMDD.csv                │
│  ② filter_news.py  关键词筛选→情绪分类        │
│       → data/daily_sentiment.csv              │
│  ③ decision.py     情绪分+行情→买卖+杠杆档位  │
│       → data/decision_{date}.csv              │
│  ④ sim_account.py  模拟撮合(T+1/手续费/熔断)  │
│       → data/portfolio.csv, trade_log.csv     │
│  ⑤ daily_report.py 生成HTML报告+邮件推送      │
│       → reports/report_{date}.html            │
└──────────────────────────────────────────────┘
交互模型：邮件报告(主) + CSV查看(次) + 手动运行命令
```

## 数据模型

| 文件 | 核心字段 |
|---|---|
| `news_{date}.csv` | time, title, content, source, related_stocks, senti |
| `daily_sentiment.csv` | date, senti_score, total_news, pos_cnt, neg_cnt, neutral_cnt |
| `decision_{date}.csv` | date, stock, signal(买/卖/观望), leverage(1/2/3), reason |
| `portfolio.csv` | date, stock, shares, cost, market_value, cash, leverage, total_value |
| `trade_log.csv` | date, stock, action, price, shares, amount, leverage, reason |
| `reports/report_{date}.html` | 情绪总览/决策/持仓/成交/杠杆/风险 |

## 决策逻辑

**买卖信号**：
- 情绪分 > +0.3 且个股涨跌幅 > 0 → 买入（目标仓位 = 仓位上限）
- 情绪分 < -0.3 或个股均线死叉 → 卖出清仓
- 其余 → 观望

**杠杆档位**（随情绪分自动切换）：
- 情绪分 ≥ +0.6 → 3 倍
- +0.3 ~ +0.6 → 2 倍
- < +0.3 → 1 倍

**熔断机制**：3倍杠杆下市值跌超 33%（归零）→ 触发"爆仓熔断"：清仓 + 邮件告警 + 停止自动交易。待满足冷却条件自动恢复：至少 5 个交易日冷静期 + 连续 2 日情绪分转正 + 恢复后仅 1 倍杠杆起步。

**交易规则**：信号次日开盘价成交；T+1；佣金万2.5+卖出印花税0.05%（最低5元）；单票仓位上限30%；总仓位上限90%；涨停不卖/跌停不买。

## Phase 1 实施顺序（MVP）

| # | 任务 | 验证标准 |
|---|------|---------|
| 1 | 项目骨架 + git init + requirements.txt + 目录结构 | pip 安装成功，目录就绪 |
| 2 | config.py 配置模块（股票池/关键词/资金/路径/secrets 加载） | 配置类可导入，密钥不硬编码 |
| 3 | fetch_news.py 国内新闻爬取（重试3次+备用接口降级） | 拉到当日新闻≥数十条，CSV 完整 |
| 4 | filter_news.py 关键词筛选+情绪分 | 人工抽样核对 20 条分类准确 |
| 5 | decision.py 买卖+杠杆决策 | 决策 CSV 输出正确信号 |
| 6 | sim_account.py 模拟撮合（T+1/手续费/熔断/冷却恢复） | 连续 5 个交易日无异常，成交记录正确 |
| 7 | daily_report.py HTML 报告 + 邮件推送 | 报告可打开，邮件可达 |
| 8 | run_all.sh 一键运行 + crontab 注册 | 定时自动运行 |
| 9 | 前20天预热期验证（只记录情绪不交易） | 预热日志正常 |

### 每个会话（含 step 1 起）卫生检查清单
```
□ 实现步骤
□ 添加/更新测试（本阶段为日志断言脚本）
□ 运行构建（python -m compileall .）
□ 运行 lint（ruff check .）
□ 更新 docs/user 与 docs/knowledge
```
（控制台：`□ 更新 CONSOLE.md`）

## Phase 2（重要，非 MVP）

- 历史回测模式（用历史新闻 CSV 回放验证策略）
- 情绪分与指数涨跌相关性周复盘
- 熔断日志分析

## Phase 3（可选）

- Telegram 频道接入（需境外跳板，另行评估成本与合规）
- 大模型新闻分类升级（DeepSeek API，预算 0~30 元/月）
- 情绪分 + 机器学习联合决策

## 已砍掉的功能（决定不做什么）

- ❌ Web 仪表盘（实时 Web 服务）→ 改为静态 HTML 报告（零安全面）
- ❌ Telegram 重写入 MVP（境内服务器无法直连）
- ❌ 真实资金交易（硬约束红线）
- ❌ Twitter/X 数据源（反爬与 ToS 风险高，优先级最低）
- ❌ 多用户/分享功能（仅自己用）

## Non-goals（明确不做）

- 不做真实资金/真实下单
- 不做高频交易
- 不做期货/期权
- 不做移动端 App
- 不承诺盈利，仅为学习工具

## 配置项（config.py 规划）

| 配置 | 默认值 | 说明 |
|---|---|---|
| STOCKS | 600519.XSHG / 000858.XSHE / 601318.XSHG / 600036.XSHG | 股票池 |
| INIT_CASH | 100000 | 模拟初始资金 |
| SENTI_BUY_THRESHOLD | 0.3 | 买入情绪阈值 |
| SENTI_SELL_THRESHOLD | -0.3 | 卖出情绪阈值 |
| LEVERAGE_HIGH | 3 | 高置信杠杆 |
| LEVERAGE_MID | 2 | 中置信杠杆 |
| LEVERAGE_LOW | 1 | 默认杠杆 |
| COOLDOWN_DAYS | 5 | 熔断冷却日数 |
| RECOVERY_SENTI_DAYS | 2 | 恢复所需连续转正日数 |
| MAX_POSITION_RATIO | 0.30 | 单票仓位上限 |
| MAX_TOTAL_RATIO | 0.90 | 总仓位上限 |
| COMMISSION_RATE | 0.00025 | 佣金率 |
| STAMP_TAX | 0.0005 | 印花税(卖出) |
| MIN_COMMISSION | 5 | 最低佣金 |