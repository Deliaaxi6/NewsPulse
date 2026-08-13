# NewsPulse（闻风而动）- 新闻情绪驱动的量化学做小系统

> 每日抓取 A 股新闻 → 关键词情绪评分 → 自动决策 → 模拟撮合（10 万虚拟资金）→ 复盘报告
>
> 学生自制量化学习项目，不构成任何投资建议。

## 项目是什么

NewsPulse 是一套**全自动学习型量化模拟交易系统**：每天收盘后自动拉取东财新闻，对"贵州茅台/五粮液/中国平安/招商银行"四只股票的新闻做关键词情绪分类，结合行情趋势给出买卖信号与杠杆档位，在 10 万虚拟账户里模拟撮合（T+1、手续费、熔断保护），生成 HTML 复盘报告。

- 100% 模拟盘，实盘本金 100 元因合规红线永不交易
- 学习目标：跑通"新闻 → 情绪 → 决策 → 成交 → 复盘"完整数据管道
- 全自动化：工作日 16:30 crontab 触发，无需人工干预

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.10+（服务器）/ 3.13（本地） |
| 数据 | akshare（东财/新浪，免费） |
| 处理 | pandas（纯 CSV 存储，人眼可读） |
| 调度 | crontab |
| 报告 | 静态 HTML（零安全面） |
| 通知 | 邮件（复用 send_email.py） |

## 数据流

```
[16:30 crontab 触发 (工作日)]
 ① fetch_news.py   拉东财快讯 + 4只个股新闻 → data/news_{date}.csv
 ② filter_news.py  关键词筛选 + 情绪分类（否定翻转/程度加权）
                      → data/daily_sentiment.csv
 ③ decision.py     情绪分 + 行情 → 买卖信号 + 杠杆档位(1/2/3倍)
                      → data/decision_{date}.csv
 ④ sim_account.py  模拟撮合(T+1/手续费/停牌屏蔽/熔断) + 次日预测校验
                      → data/portfolio.csv, trade_log.csv, predictions.csv
 ⑤ daily_report.py 生成 HTML 报告 → reports/report_{date}.html
```

## 目录结构

```
quant_news/
├── src/                  # 模块源码
│   ├── fetch_news.py     # ① 新闻爬取（东财主 + 新浪降级）
│   ├── filter_news.py    # ② 关键词筛选 + 情绪分类
│   ├── decision.py       # ③ 决策 + 杠杆
│   ├── sim_account.py    # ④ 模拟撮合 + 熔断 + 预测校验
│   ├── circuit_breaker.py#     熔断器（核心安全阀）
│   ├── backtest.py       #     历史回测（无前视）
│   ├── daily_report.py   # ⑤ HTML 报告
│   ├── config.py         # 配置（不含密钥）
│   └── run_all.py        # 一键入口
├── tests/                # 测试（run_tests.py 统一入口）
├── data/                 # CSV 数据（git 忽略）
├── reports/              # HTML 报告（git 忽略）
├── logs/                 # 运行日志（git 忽略）
├── docs/                 # 文档（架构/决策/gap 分析/用户指南）
├── requirements.txt
└── ROADMAP.md / PROGRESS.md / CLAUDE.md
```

## 快速开始（本机开发）

```bash
git clone <repo-url> && cd quant_news
pip install -r requirements.txt
python src/run_all.py              # 一键跑全链路
python tests/run_tests.py          # 跑全部测试（32 用例）
```

单模块运行（可指定日期）：
```bash
python src/fetch_news.py --date 2026-08-13
python src/backtest.py --start 2026-08-01 --end 2026-08-13
```

> ⚠️ Windows 下请用 `python` 而非 `py`（本机 `py` 指向无 pandas 的旧 Python）。

## 核心逻辑速览

- **情绪分**：`(利好数 - 利空数) / 总数`；关键词命中 + 否定词 20 字窗口翻转 + 程度词加权
- **买卖信号**：情绪 > +0.3 且个股涨 → 买入；情绪 < -0.3 → 卖出；其余观望
- **杠杆档位**：情绪 ≥0.6 → 3 倍；0.3~0.6 → 2 倍；<0.3 → 1 倍
- **熔断保护**：3 倍杠杆回撤 ≥33% → 清仓 + 冷却 5 日 + 连续 2 日情绪转正才恢复（二次熔断冷却翻倍，恢复初期锁 1 倍）
- **交易规则**：信号次日开盘价成交；T+1；佣金万 2.5（最低 5 元）+ 卖出印花税 0.05%；单票 ≤30%、总仓 ≤90%；涨停不卖/跌停不买；停牌/一字板显式屏蔽
- **预测校验**：隔日验证决策预测（up/down/flat）命中率，报告展示"策略预测准确率"
- **宁缺毋假**：行情缺失时预测值为 none，不假装 0%

## 已知限制

- 关键词规则情绪分类（非 LLM），分类精度有限；大模型升级留待 Phase 3
- 本机东财行情接口被代理拦截时自动降级新浪日K
- 熔断恢复需冷却条件满足，修改恢复逻辑时必须保留防循环设计

## 文档

| 文档 | 内容 |
|---|---|
| ROADMAP.md | 愿景 / 硬约束 / Phase 1-3 计划 |
| PROGRESS.md | 实施进度与会话日志 |
| CLAUDE.md | AI 协作规则 + 快速命令 |
| docs/ARCHITECTURE.md | 模块契约 / 决策引擎 / 熔断设计 |
| docs/DECISIONS.md | 12 项设计决策（D1-D12） |
| docs/gap-analysis.md | 对照开源项目的缺陷分析与修复记录 |
| docs/user/* | 面向使用者的指南（每日 / 配置） |

## 免责声明

本项目仅为个人学习量化和自动化编程所用，全部为模拟交易，不构成任何投资建议，不对任何损失负责。