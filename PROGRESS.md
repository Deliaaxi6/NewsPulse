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
- G6 资金面（adata）✅ / InStock 融入进行中（筹码分布 ✅ → 多代理+Cookie ✅ → 形态61种 ✅ → 策略模板 → 综合选股）

## Phase 2 (重要)

- [ ] 历史回测模式
- [ ] 情绪分与指数涨跌相关性周复盘
- [ ] 熔断日志分析

## Phase 3 (可选)

- [x] Telegram 频道接入（服务器 mihomo 代理已通，2026-08-14 实测双通道推送）
- [x] 大模型新闻分类升级（DeepSeek API）— 已实测：key 环境变量 NEWSPULSE_DS_KEY 已配置，2026-08-14 全量 371 条真实分类成功，同日重跑缓存幂等零调用
- [x] 情绪分+机器学习联合决策 — 框架就绪（纯 numpy 逻辑回归，数据 ≥20 交易日自动启用），当前数据不足自动跳过

---

## 会话日志（从设计阶段开始记录）

### 2026-08-14 — 方案 A/B/C 落地（个股止损 / 个股情绪 / 追涨修复）+ 服务器环境对齐
- ✅ 方案 A 个股止损：`STOP_LOSS_RATIO=0.08` + `STOP_COOLDOWN_DAYS=5`（config.py）；sim_account 新增 `_stop_cooled()`/`stop_loss_signal()`，持仓成本回撤≥8% 生成止损卖出（涨停不卖/一字板保护沿用），卖后写 stop_loss_log.csv 且 5 个交易日内禁止再买该股；test_trading 20/20（回撤9%触发/7%不触发/无行情跳过/空仓跳过/零成本跳过/冷却窗口 4 例）
- ✅ 方案 B 个股情绪：filter_news 新增 `stock_sentiment()`（related_stocks 6 位代码且在当日选股池内才分组，市场新闻 URL 不参与）写 `data/stock_sentiment_{date}.csv`；decision 新增 `stock_senti_map()`，个股新闻 ≥3 条（`STOCK_SENTI_MIN`）时用个股情绪覆盖市场情绪参与信号判定与置信度（`w=min(1, 条数/10)`），杠杆仍用市场分，reason 追加"| 个股情绪: +x.xx(N条)"；tests/test_stock_sentiment.py 新建 20/20，run_tests.py 注册第 17 套件
- ✅ 方案 C 追涨修复：select_stock 新增 `_filter_market_df()`（非ST/涨幅0~9.9%/量比>1.5/成交额>2亿）+ `_market_pool()`（东财 spot_em 全市场一次请求，失败降级纯涨停池）+ `_merge_pools()`（涨停池优先去重排序，写 CSV 剔除内部 source 列）；decision 新增 `CALLBACK_STRATS={"回踩年线","低波动启动","无大跌回踩"}` + `_is_callback()`（回调策略不要求当日上涨，reason"回调企稳"）+ `OVERBOUGHT_LBC=3`/`RSI_OVERBOUGHT=80` + `_overbought()`（buy 后 confidence-0.1 +"（超买降权）"）；test_select_stock 增补过滤/合并用例
- ✅ 服务器环境对齐：pandas-ta 0.4.x 要求 Python≥3.12（服务器 py3.11 无可用版本，PyPI 旧版已 yank）→ kline_patterns 新增 `_detect_talib_direct()` 直调 TA-Lib 61 个 CDL 函数（无需 pandas-ta）；服务器 `pip install TA-Lib 0.6.8`（manylinux wheel 捆绑 C 库）；本地两路径输出一致，服务器 indicators 16/16
- ✅ 验证：本地全量回归 17 suite ALL PASSED；服务器全量 17 suite ALL PASSED；服务器 run_all 实测——快照过滤失败降级纯涨停池（fail-open ✓）、个股情绪 20 只入库（000887 个股 -0.40 触发 sell 信号，覆盖市场 -0.05）、61 形态生效、报告+邮件+Telegram 推送成功
- ✅ 提交：`27dba89`(A 止损) → `351ccea`(B 个股情绪) → `c42f21a`(C 追涨+talib 直调)
- 📌 待办：全市场快照接口偶发 RemoteDisconnected（东财限流，已有降级链）；Telegram 偶发 SSL EOF（代理抖动，重试后成功）；止损信号需真实持仓后观察

### 2026-08-14 — 服务器部署完成（101.96.196.187, CentOS 7）
- ✅ 环境：Miniconda Python 3.11.9（/opt/miniconda3，glibc 2.17 无法 pip 装 pandas → conda install pandas/numpy 规避源码构建）；conda env `np`（Python 3.11.13 / pandas 2.3.2 / akshare 1.18.91 / adata 2.9.5）；项目上传 /opt/newspulse（含 email-notification 邮件脚本 + config.json chmod 600）
- ✅ 密钥：/opt/newspulse/secrets.env（chmod 600）注入 TG token/chat_id/channel、NEWSPULSE_DS_KEY、邮件脚本路径、TG_PROXY=http://127.0.0.1:7897
- ✅ 境外代理：机场订阅接口须带 Clash UA 才返回数据（verify_mode.htm 无 UA 时返回空）→ 本机下载 mihomo v1.19.29 compatible（旧 glibc）+ geoip.metadb/geosite.dat（服务器 GitHub 不可达，本机出墙下载上传）→ /opt/mihomo/config.yaml（mixed-port 7897，订阅原样）→ systemd 自启（mihomo.service active）；api.telegram.org 经代理 302 可达
- ✅ Telegram 实测：send_text 私聊 + send_to_channel 频道双通道 OK（此前 404 为测试调用姿势错误——send_to_channel 签名 (text, token=None)，把频道 ID 误传为 text/token；生产 daily_report 单参调用正确，非代码 bug）
- ✅ 全链路 run_all 实测：新闻 370 → LLM 分类全命中缓存（0 API 调用）→ 情绪 -0.0459（利0/空17/中353）→ 决策 20 条 hold 杠杆1倍（东财快照失败降级新浪 ✓）→ 撮合一字板屏蔽（fail-open ✓）→ 报告 report_2026-08-14.html 生成 + 邮件推送成功；portfolio.csv 100000 初始化
- ✅ crontab：`5 9 * * 1-5` 工作日 9:05 全链路（set -a + secrets.env + np 解释器 → logs/cron.log）
- 📌 待办：ML ≥20 交易日自动生效（数据积累中）；20 天预热期验证；情绪分-指数相关性周复盘；master→main 改名（可选）；mihomo 订阅到期需手动更新 config

### 2026-08-14 — Phase 3：DeepSeek 全量新闻分类 + ML 联合决策框架
- ✅ src/llm_sentiment.py 新建（DeepSeek 全量新闻二次分类）：deepseek-v4-flash 非思考模式、temperature=0、strict JSON（bull/bear/neutral+confidence）；批处理 BATCH=15；同日按内容 md5 hash 缓存 data/llm_cache_{date}.json（同日重跑幂等零计费）；单批失败该批保留关键词规则、连续 3 批失败本次熔断；key 环境变量 NEWSPULSE_DS_KEY（未配置跳过，fail-open）
- ✅ src/config.py 新增 DEEPSEEK_API_KEY/MODEL/API（默认 https://api.deepseek.com，国内直连无需代理）
- ✅ src/filter_news.py 集成：classify(df, date_str) 关键词规则分类后 LLM 二次覆盖（LLM 非 None 才覆盖），LLM 覆盖率打印
- ✅ tests/test_llm_sentiment.py 新建 9 用例（未配置跳过/成功映射/缓存幂等/批失败降级/连续3批熔断/JSON解析失败/集成覆盖/无key保留规则），全过
- ✅ src/ml_advisor.py 新建（ML 联合决策框架）：纯 numpy 逻辑回归（sklearn 未安装，未引入新依赖）、L2+标准化+2000 轮梯度下降；特征 5 维（senti_score/mom/bull_ratio/total_news/ma3，仅本地 CSV 无网络依赖）；标签=次日总资产下跌（portfolio.csv）；数据 <20 交易日自动跳过（fail-open）；模块级同日训练缓存；p_drop≥0.6 → confidence -0.1 + reason 追加（不改主规则/杠杆/熔断）
- ✅ src/decision.py 集成：decide() 每日取一次 advice，intervene 时降 confidence 追加 reason（与 G6/G8 同级辅助因子）
- ✅ tests/test_ml_advisor.py 新建 10 用例（无数据跳过/不足20天跳过/合成数据训练收敛/干预阈值/缓存复用/上涨市不干预/特征零值安全/缺文件fail-open/decision 集成干预与未启用），全过
- ✅ 全量回归 15 suite ALL PASSED；真实链路：filter_news 无 key 降级正常（情绪 0.097 与历史一致，幂等）、ml_advisor 数据不足跳过、decision 2026-08-14 全 hold 正常
- ✅ 真实调用联调（用户提供 key，setx NEWSPULSE_DS_KEY 持久化）：实测发现 v4-flash 默认思考模式导致两坑——① 不加 response_format 时输出自由文本；② reasoning.enabled=false 参数不生效，15 条/批思考耗尽 max_tokens=512 时 content 为空串致 JSON 解析失败。调参修复：max_tokens=4096 + reasoning_effort=low（省 ~35% tokens）+ response_format=json_object；实测 371 条全量分类成功（第一批偶发输出空数组，熔断计数被后续成功批重置，未误熔断），同日重跑 371 条全命中缓存零调用（幂等计费验证 ✓）
- ✅ 回测模式完善（登记未处理项）：src/backtest.py 选股池改为优先当日 select_{T}.csv（与生产 select_stock 链路一致，T-1 涨停池盘前可用，严格无前视），缺失/空/读取失败回退 config.STOCKS 基准池；行情按需加载（select 池股票可能不在 STOCKS）；tests/test_backtest.py 新建 6 用例（池优先/缺失回退/空文件回退/读取失败回退/池外股票按需加载/全流程走 select 池），全过；真实区间回测 2026-08-13~14 正常（情绪<0.3 无交易）
- ✅ Telegram 频道接入（Phase 3 剩余项）：src/config.py 新增 TELEGRAM_CHANNEL（环境变量 NEWSPULSE_TG_CHANNEL，@username 或频道负 ID）；src/telegram_push.py 新增 send_to_channel()（未配置跳过 fail-open，复用 send_text 仅换 chat_id）；src/daily_report.py 报告生成后同时推私聊+频道；tests/test_telegram.py 扩至 11 用例（频道未配置跳过/chat_id=频道/失败降级），全过；实测：getUpdates 探测到频道「NewsPulse 日报」(ID -1004352433163, 私密无username)，setx NEWSPULSE_TG_CHANNEL 持久化，send_to_channel 推送成功（用户已在频道收到日报消息）
- 📌 待办：ML 需积累 ≥20 个交易日数据后自动生效；服务器部署 + crontab（Phase 1 任务 8，需服务器信息）；20 天预热验证（任务 9，等数据）；情绪分-指数相关性周复盘（需数据）；master→main 改名（可选）

### 2026-08-13 — 前端预览页升级：Chart.js dashboard 模板（GitHub 拉取改造）
- ✅ 选型：GitHub 开源单文件模板 KPI_Analyzer_Dashboard（暗色主题+KPI卡片+趋势图），克隆至 Temp\opencode\ 供改造参考（不并入项目）；备选 IDV-App 一并拉取对比
- ✅ 依赖本地化（无 CDN 依赖，离线可用）：Chart.js 4.4.7（205KB）+ chartjs-plugin-annotation 3.0.1（34KB）→ `src/assets/`；模板的 xlsx（Excel 导入）功能剔除
- ✅ src/daily_report.py 重构：PAGE 换暗色 dashboard（KPI 卡片×4：情绪分/新闻量/总资产/决策数 + 3 图：情绪趋势折线（≥7天加7日均线）/新闻量柱状/情绪分布环形 + 原 6 节表格保留）；数据以 JSON 注入（`__CHART_JSON__` 占位符 replace，避免 format 大括号转义）；新增 chart_data()/score_color()（A股红涨绿跌）
- ✅ 修复 subprocess GBK 解码异常：邮件脚本 UTF-8 中文输出在 text=True 下按 GBK 解码崩溃 → encoding='utf-8', errors='replace'
- ✅ 数据卫生：daily_sentiment.csv 存量 7 行同日 → 收拢为 1 行（取当日最后一条）；chart_data() 按 date 去重防趋势图重复点
- ✅ 测试 13/13 新增（资源存在/模板元素/图表结构/去重/占位符残留），全量回归 ALL PASSED；报告 9755B 生成 + 邮件推送正常
- 📌 未处理：run_all 每次运行向 daily_sentiment 追加同日记录（写入侧去重留待后续任务）
- 📌 下一步：InStock 融入「综合选股」

### 2026-08-13 — InStock 融入：经典策略模板（core/strategy 10 策略）完成
- ✅ src/strategies.py 新建（约 280 行）：10 策略逐条对照 InStock 源码（instock/core/strategy/*.py，2023-03 版）转写——海龟突破(turtle_trade)/持续上涨(keep_increasing)/放量上涨(enter)/平台突破(breakthrough_platform)/回踩年线(backtrace_ma250)/高潮跌停(climax_limitdown)/高紧旗形(high_tight_flag)/低波动启动(low_atr)/无大跌回踩(low_backtrace_increase)/停机坪(parking_apron)；数据不足或行情失败宁缺毋假返回 False
- ✅ 关键阈值照源码核对：放量上涨 p_change≥2%/阳线/成交额≥2亿/量比≥2；跌停<-9.5% 且量比≥4；回踩年线≥250日+回踩距最高10-50天+量比>2+回撤<0.8；海龟=末收盘≥窗口最高；low_atr 振幅比值>1.1（110% 振幅）；停机坪=涨停后3日横盘±3% 且涨停日须满足海龟（全量 origin_data，见 bug 修复）
- ✅ fetch_kline：新浪日K（net_guard 降级链）≥300 天含 volume/amount，p_change 缺失时自行计算（indicators 120 天无 volume → 策略独立拉取）
- ✅ src/decision.py 集成：strategy_factor(sym) + reason 追加"| 策略: X/Y" + buy 时每条 +0.02 confidence 封顶 +0.1
- ✅ 修复转写 bug 2 处：keep_increasing 须先整 df rolling(30) 再 dropna+tail(30)（原只在 tail 上 rolling 全 NaN）；parking_apron 的 turtle_trade 须基于全量 origin_data 截止涨停日（原误用 tail(15) 窗口内前段，导致该策略永远不命中）
- ✅ tests/test_strategies.py 新建 32 用例（命中/未命中/10 策略短 df 边界/缺列不崩溃）挂载 run_tests.py；全量回归 10 suite ALL PASSED
- ✅ 实测 decision 2026-08-13：600519 命中「策略: 平台突破」，其余宁缺毋假；东财快照失败自动降级新浪日K
- 📌 下一步：InStock 融入「综合选股」（全市场扫描选标的，取代硬编码 STOCKS 观察池）

### 2026-08-13 — DSA 参考项落地：大盘护栏 + 推送降噪 + 幂等存储
- ✅ 背景：调研 daily_stock_analysis（62.7k stars，LLM 付费驱动）后按用户选择落地 1/3/4 三项（否定词检测评估为不适用：NewsPulse 关键词表无"买入/加仓"动作词，现有 NEGATION 体系已覆盖否认翻转；多市场/Web 工作台/Agent 问股不适用）
- ✅ src/market_env.py 新建（大盘环境护栏，参考 daily_market_context_guardrail）：新浪指数日K降级链（东财指数快照本机被拦截）+ 乐咕涨跌家数（长表 item/value，模糊匹配 上涨/下跌/涨停/跌停）→ 弱势判定（任一指数≤-1.5% 或 跌家/涨家≥2）；guard() 弱势 buy→hold、情绪分/置信度封顶 0.5、reason 追加"市场弱势已软化"；数据全失败返回 None 宁缺毋假
- ✅ src/decision.py 集成：decide() 调 market_env，buy 分支后 guard（predict 同步 flat），reason 追加"| 市场: …"；杠杆计算用软化后分数（弱势自动降杠杆）
- ✅ src/daily_report.py 推送降噪（参考 notification_noise）：内容指纹 md5(日期+文件内容) 同日同内容跳过重发；标记文件读写失败 fail-open 照常推送；修正过程：首版用 mtime+size 指纹被"报告每次重生成"击穿，改内容级指纹
- ✅ src/filter_news.py 幂等：daily_sentiment 写入侧按 date UPSERT（同日重跑只保留最新一条），解决 demo 每日追加同日行问题
- ✅ 实测：decision 2026-08-13 reason 含"市场: …（弱势，信号软化处理）"（当日指数+0.32%但跌4041/涨1085，家数判定捕获指数失真行情）；filter_news 重跑两次同日仅 1 行；daily_report 第二次运行"已推送过，跳过重复推送"
- ✅ 测试：test_market_env.py 新建 13 用例（weak 判定/guard/除零/None）；test_daily_report.py 15/15（+4 降噪用例）；全量回归 11 suite ALL PASSED
- ✅ 未处理事项收尾（用户确认范围）：net_guard 源级熔断 + decision.py --date 参数统一
  - net_guard：单源连续失败 3 次 → 熔断 300s 跳过（DSA CircuitBreaker 参考）；修复 2 处实现 bug：_is_cooled 过期清理 pop 副作用导致计数被清空（改纯查询）、_record_fail 冷却期重建计数；test_net_guard 19/19（+5 熔断用例：3 次熔断/冷却跳过走次源/成功清除/冷却过期恢复/计数隔离）
  - decision.py：__main__ 支持 `--date 2026-08-13`（兼容位置参数），与 CLAUDE.md 文档统一；实测写入 decision_2026-08-13.csv
  - 全量回归 11 suite ALL PASSED；fetch_news/filter_news/sim_account/daily_report 同类位置参数问题留待后续统一
- ✅ InStock 融入「综合选股」（全市场扫描选标的，取代硬编码 STOCKS 观察池，用户确认：涨停池口径 + 完全替换）
  - 新增 src/select_stock.py：东财涨停池（stock_zt_pool_em，T-1 基准日回退 7 天）→ 按连板数/封板资金排序取前 MAX_SCAN=20 → 逐只 strategies.detect（10 策略模板）→ data/select_YYYY-MM-DD.csv（code/symbol/name/lbc/seal_amount/strategies/score）；空池/接口失败 fail-open 写空 CSV；load_pool() dtype str 保前导 0
  - 生产链路切换：fetch_news（空池仅抓市场新闻）/decision（decide/fetch_spot 接收 pool）/sim_account（报价池=观察池∪实际持仓，修复 0 股持仓混入）/daily_report（names 映射+cyq 行用池）/run_all（选股前置步骤）；config.STOCKS 保留为 backtest 回测基准池（加注释）
  - tests/test_select_stock.py 16/16（排序/前导0/MAX_SCAN 截断/空池 fail-open/接口异常/非交易日/load_pool 缺文件）；全量回归 12 suite ALL PASSED
  - 实测 2026-08-14 全链路：选股 20 只（涨停池 08-13，策略命中如百花医药 7连板）→ 决策 20 条（东财快照失败自动降级新浪）→ 撮合（一字板屏蔽正常）→ 报告+邮件
- ✅ 生产链路 4 模块 CLI 参数统一（fetch_news/filter_news/sim_account/daily_report 均支持 `--date YYYY-MM-DD`，兼容位置参数，与 decision.py 一致）；实测 fetch_news --date 2026-08-14 抓 371 条（含 20 只动态池个股新闻）+ filter_news --date 情绪 0.097；回归 12 suite ALL PASSED
- ✅ 熔断审查修复（缺陷1严重+缺陷3审计；缺陷2排期）：触发杠杆改为 max(当日决策, 持仓杠杆)（_top_leverage，持仓期 hold 回撤33%可触发）；持仓买入记录真实杠杆、portfolio 行 leverage 不再恒 1；熔断事件（触发/冷却推进/恢复）落盘 logs/circuit.log；test_trading +3 用例（13/13），回归 12 suite ALL PASSED
- ✅ 熔断缺陷2修复（repeat_cool 窗口改交易日口径）：新增 fund_flow.trading_days_between()（adata 交易日历，日历不可用返回 None）；circuit_breaker._is_repeat() 交易日≤10 判重复，日历不可用降级自然日（fail-open）；test_circuit +4（14/14）、test_fund_flow +4（含倒序/跨休市/空日历），回归 12 suite ALL PASSED
- ✅ Telegram 推送接入（Phase 3 基础版）：新增 src/telegram_push.py（sendMessage + 日报摘要 HTML，代理默认走本机 Clash 127.0.0.1:7897，实测 api.telegram.org 经此可达）；config 新增 TELEGRAM_BOT_TOKEN/CHAT_ID/API/PROXY（环境变量注入，未配置 fail-open 跳过）；daily_report 报告生成后追加推送；requirements 显式声明 requests；test_telegram 8/8，回归 13 suite ALL PASSED
- ✅ Telegram 推送实测通过：bot newspulse_daily_bot（token 已配用户环境变量 NEWSPULSE_TG_TOKEN），chat_id 6359097393（NEWSPULSE_TG_CHAT_ID），日报摘要 sendMessage 推送成功；服务器部署时改走 secrets.json 注入
- ✅ 公开仓库推送：Deliaaxi6/NewsPulse（public，https://github.com/Deliaaxi6/NewsPulse），
  提交 926ff46（综合选股/熔断修复/CLI 统一/Telegram 推送 33 文件），
  推送前扫描确认无 token/密钥/私钥，data/reports/logs 由 .gitignore 排除
- 📌 下一步：情绪分周复盘（需数据积累）/ 日报推送对接定时任务

### 2026-08-13 — InStock 融入：K线形态扩展至 61 种（talib 引擎）
- ✅ 引擎重写 src/kline_patterns.py：首选 pandas-ta `cdl_pattern(name='all')`（底层 TA-Lib C 库 0.6.4），61 种 CDL 形态全量识别；TA-Lib 缺失时降级纯 pandas 8 种 `_detect_legacy`（宁缺毋假）
- ✅ TALIB_CN_MAP 中文名照 InStock（instock/core/tablestructure.py 417-533 段）逐条核对；实测 62 列（61 talib + pandas-ta 2 特列）**全部映射、无 CDL_ 列名泄漏**
- ✅ 补充 2 个 pandas-ta 特有列：CDL_DOJI_10_0.1→"十字"（doji 参数化变体）、CDL_INSIDE→"母子线"（inside 内含线，HARAMI 同义）
- ✅ 测试断言按 talib 0.6.4 实际行为重写：旧"锤头"构造被判为梯底（源码核对 4 条件：实体<前10根实体均值 / 下影>实体 / 上影<前10range×0.1 / 实体贴近前日低点），已替换为逐条满足的 HAMMER 构造（实测命中）；十字星改测极窄 doji（实测 `['十字','长脚十字','黄包车夫']`）
- ✅ 回归：indicators 16/16，全量 ALL PASSED；compileall src+tests 通过；ruff 未安装（沿用待部署时执行）
- 📌 下一步：InStock 融入「经典策略模板」（放量上涨/回踩年线/海龟等）

### 2026-08-13 — G6 资金面 + 交易日历 + 腾讯降级（adata 融入）完成
- ✅ 引入 adata 2.9.5（pip 已装，requirements.txt 已登记）——用户授权后安装
- ✅ src/fund_flow.py 新建：两融余额趋势（±1% 阈值判 回升/回落/平稳）+ 北向资金信号 + 交易日历；全部失败不阻断（宁缺毋假）
- ✅ 实测发现：北向资金每日净买入 **2024-08 起官方停发**（north_flow 全 0），宁缺毋假标注 unavailable 不硬造；两融 securities_margin 需带 start_date 否则空（披露滞后约一周）
- ✅ src/decision.py 集成 G6：资金面辅助因子（confidence ±0.05 + reason 摘要），不改买卖主规则/杠杆/熔断
- ✅ src/fetch_news.py：交易日历判断非开市日早退；日历不可用仍继续爬取（避免误判）
- ✅ src/sim_account.py：行情降级链升级 东财→新浪→**腾讯分时**（adata qq_market，实测可用仅价格 pct=None）；一字板/涨跌停/预测校验全部 pct=None 安全
- ✅ 测试 11/11 新增，回归 63/63 全绿；compileall 通过
- ✅ run_all 实测：资金面摘要真实生效（"两融余额回升+1.70%; 资金面部分数据缺失跳过"）
- ⚠️ 排查回测 0→4 笔假象：根因是 data/ 残留 3 个模拟新闻文件（news_2026-08-10/11/12，非本次代码回归），已清理，回测恢复基线 0 交易
- 📌 下一步：InStock 融入（筹码分布/多代理+Cookie/形态61种/策略模板/综合选股）

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