# PROGRESS — NewsPulse 实施进度

> 每次会话结束（或完成一个阶段）更新本文件。格式：`- [x]` 完成 / `- [ ]` 未完成 + 日期。

## Phase 1 (MVP) 实施状态

- [x] 任务1：项目骨架 + git init + requirements.txt + 目录结构（2026-08-13 git init 完成）
- [x] 任务2：config.py 配置模块（已分离熔断/G5 常量）
- [ ] 任务3：fetch_news.py 新闻爬取
- [ ] 任务4：filter_news.py 关键词筛选+情绪分
- [ ] 任务5：decision.py 决策+杠杆
- [ ] 任务6：sim_account.py 模拟撮合+熔断
- [ ] 任务7：daily_report.py 报告+邮件
- [ ] 任务8：run_all.sh + crontab 注册
- [ ] 任务9：前20天预热期验证

### 当前任务
- Phase 1 收尾：git init ✅ / tests 目录 ✅ / ruff 检查 ⏳（本机未装 ruff，待装或部署时执行）

## Phase 2 (重要)

- [ ] 历史回测模式
- [ ] 情绪分与指数涨跌相关性周复盘
- [ ] 熔断日志分析

## Phase 3 (可选)

- [ ] Telegram 频道接入（需境外跳板评估）
- [ ] 大模型新闻分类升级（DeepSeek API）
- [ ] 情绪分+机器学习联合决策

---

## 会话日志（从设计阶段开始记录）

### 2026-08-13 — G8 技术指标 + K线形态 完成
- ✅ src/indicators.py：MA/MACD/KDJ/RSI/BOLL 五指标（纯 pandas，无 talib）；analyze/describe；数据不足宁缺毋假
- ✅ src/kline_patterns.py：8 种高频形态（早晨之星/黄昏之星/锤头/上吊/长阳吞没/十字星/射击之星/乌云盖顶）
- ✅ src/decision.py 集成：辅助因子（均线多头共振 confidence+0.1 + reason 技术摘要），不改买卖主规则/杠杆/熔断
- ✅ 修复 RSI 除零缺陷（纯上涨应=100）
- ✅ 测试 16/16 新增，回归 48/48 全绿；run_all 正常；回测结果与实施前一致（无回归）
- 📌 下一步：邮件推送 / G6 资金面 / 部署

### 2026-08-13 — Phase 1 收尾（git + tests + 卫生）
- ✅ git init + .gitignore（排除 data/reports/logs/__pycache__/secrets.json），24 文件首次暂存
- ✅ tests/ 正式测试目录（此前临时脚本在系统临时目录，已固化）：
  - tests/test_sentiment.py — 情绪分类 12 用例（含否定翻转/复合负面词保护）
  - tests/test_trading.py — G5 一字板 6 用例 + 预测校验 4 用例 + none 跳过
  - tests/test_circuit.py — 熔断器 10 用例（触发阈值/冷却推进/恢复/防循环/杠杆锁）
  - tests/run_tests.py — 统一入口
- ✅ 测试全绿：sentiment 12/12 + trading 10/10 + circuit 10/10 = 32/32
- ✅ compileall src+tests 通过
- ⚠️ 修复测试脚本自身 3 个 bug：to_csv 误用 dtype 参数 / 熔断测试时序设计错误（触发后无法再测不触发）/ predictions.csv 读取缺 dtype=str（000858 前导零丢失）
- ⚠️ ruff 未安装（规则：不擅自引入新依赖）→ 待部署时用 pip 安装后执行 `ruff check .`
- 📌 下一步：提交首次 commit（待确认）/ 邮件推送 / G6 资金面 / 部署

### 2026-08-13 — G4+G5+熔断器 完成
- ✅ G5 停牌/一字板显式屏蔽：is_one_word_board + log_blocked → blocked_log.csv（6/6 用例）
- ✅ 熔断器 src/circuit_breaker.py：33%触发/冷却5日+情绪2日恢复/防循环翻倍/恢复锁1倍杠杆（10/10 用例；修复 repeat_cool 恢复期重置缺陷）
- ✅ G4 历史回测 src/backtest.py：无前视回放，输出收益/回撤/交易明细（撮合路径验证通过 +0.36%）
- ✅ 修复严重 bug：NEGATION 词表方向错误（"承压"等负面词翻转同向负面关键词）→ 拆分 NEGATION_GENERAL/BULL_ONLY；复合负面词（未达预期）不参与翻转；12/12 情绪用例
- ✅ 修复回测估值虚亏：close 前向填充（-89.61% → 0%）
- ✅ 全流程回归通过（情绪 0.21，熔断 normal）
- 📌 下一步：G6 资金面 / G7 图表 / 邮件推送 / 部署

### 2026-08-13 — Gap 修复（三项核心，对照开源项目）
- ✅ 词库增强：否定词翻转（前后20字窗口+重叠排除+去重）+ 程度词加权（1.5x/0.5x）+ 反例词入库；9/9 边界用例通过
- ✅ 预测-校验闭环：decision 增 predict/confidence 字段；sim_account 次日回馈写入 predictions.csv；报告增"策略预测准确率"节；3/3 校验用例通过
- ✅ 宁缺毋假：行情缺失 → predict="none" + reason 明确 unavailable，不再假装 0%
- ✅ 产出 docs/gap-analysis.md（含 G4-G7 待办）
- 📌 回归：全链路通过，情绪分 0.19（词库升级后利好 46→52）
- 📌 下一步：G4 历史回测 / 熔断器 / 邮件推送 / 部署

### 2026-08-13 — Demo 完成（全链路真实数据）
- ✅ 本地 Windows 跑通全链路：东财新闻 236 条 → 情绪分 0.17 → 4 只观望 → 10万账户快照 → HTML 报告
- ✅ 发现并修复：akshare 1.18.85 列名差异（东财快讯实际为 标题/摘要/发布时间/链接）；股票代码前导零丢失 bug（dtype=str 修复）
- ✅ 新增：行情获取新浪日K降级（东财接口被本机代理拦截时自动降级）
- ⚠️ 本机东财行情接口（82.push2.eastmoney.com）被代理拦截，已降级处理；服务器直连应正常
- 📌 下一步：Phase 1 任务 2/3 完善（config 拆密钥、异常处理、crontab 部署）

### 2026-08-10 — 设计完成（spec-skill 全流程）
- ✅ 完成约束收集（Step 1）：12 项硬约束全部确认
- ✅ 完成命名与愿景（Step 2）：项目名 NewsPulse，愿景锁定
- ✅ 完成技术栈（Step 3）：Python 全家桶 + 服务器 3.10+
- ✅ 完成功能设计（Step 4）：5 模块管线确认，静态 HTML 仪表盘
- ✅ 完成愿景检验（Step 5）：成立
- ✅ 完成架构与行为（Step 6）：数据模型/密钥生命周期/8项边界场景/熔断自动恢复锁定
- ✅ 完成运维对账（Step 7）：边际成本 ¥0/月，git+手动更新
- ✅ 完成文档套件（Step 8）：ROADMAP/CLAUDE/PROGRESS/DECISIONS/ARCHITECTURE/用户文档/知识文档
- 📌 下一步：Phase 1 任务 1（项目骨架）