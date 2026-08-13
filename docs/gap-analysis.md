# Gap Analysis — NewsPulse 缺陷对照与修复记录

> 日期：2026-08-13 | 对照来源：GitHub 开源项目（astock-watch / a-share-short-decision / quant-ashare 等）
> 状态：三项核心已修复 ✓，其余列入后续

## 修复的缺陷（三项核心）

### G1. 情绪词库过于简陋 → 已修复（2026-08-13）
**问题**：仅关键词命中判断，无否定词/程度词处理。
- 反例："增长放缓"会因命中"增长"误判利好
- "业绩不及预期"若命中"超预期"字面会误判利好

**修复**（`config.py` + `filter_news.py`）：
- 新增 `NEGATION_WORDS`：否定词后 20 字内关键词极性翻转
- 新增 `INTENSIFY_STRONG` / `INTENSIFY_WEAK`：程度加权 1.5x / 0.5x
- 新增反例词进词库："不及预期"、"低于预期"、"亏损扩大"、"市值缩水"
- `classify_text` 改为 `score_text`（返回带符号分数），>0 利好 / <0 利空 / =0 中性

### G2. 无预测-实际校验闭环 → 已修复（2026-08-13）
**问题**：trade_log 只记录成交，无法评估策略好坏（参照 kenera 的 `compare_prediction_with_market`）。

**修复**（`decision.py` + `sim_account.py` + `daily_report.py`）：
- 决策新增 `predict`（up/down/flat/none）+ `confidence` 字段
- `sim_account.validate_predictions()`：次日行情回馈，写入 `predictions.csv`
- 命中规则：up→实际涨>0 / down→实际跌<0 / flat→|涨跌幅|<1%
- 报告新增"策略预测准确率（近20条）"表格

### G3. 数据降级策略不明确 → 已修复（2026-08-13）
**问题**：行情缺失时 `change=0.0` 假装无涨跌，是隐式编造数据（参照 kenera 宁缺毋假）。

**修复**（`decision.py`）：
- 行情缺失的股票：`predict="none"`，reason 明确"行情unavailable，宁缺毋假，跳过决策"
- 不参与预测统计，不参与买卖判断
- 主源（东财）失败 → 降级新浪日K（真实数据）→ 仍失败才 unavailable

## 待办缺陷（未实施）

### G4. 无历史回测模式 → 已修复（2026-08-13）
- `src/backtest.py` 新建：历史新闻 CSV 回放 filter→decision→sim，严格无前视（T 日决策 → T+1 开盘成交）
- 输出：期末资金/收益率/峰值/最大回撤/交易明细；估值用最近收盘价前向填充
- 用法：`python src/backtest.py --start 2026-08-01 --end 2026-08-13`

### G5. 停牌/一字板显式屏蔽 → 已修复（2026-08-13）
- `is_one_word_board()`：open==high==low 且涨跌幅≥9% 判一字板，不可成交
- `log_blocked()`：屏蔽明细（停牌/一字板/涨停不卖/跌停不买）写入 blocked_log.csv
- 6/6 边界用例通过（含 T 字板不误判）

### G4-FIX. 回测估值缺陷 → 已修复
- 缺失日 close 用前向填充（`_latest_close`），修复虚亏 -89.61% → 0%

### 熔断器（核心安全阀）→ 已实现（2026-08-13）
- `src/circuit_breaker.py`：3倍杠杆回撤≥33% 触发 → 清仓+冷却；恢复需冷却5日+连续2日情绪转正；防循环-10日窗口内二次熔断冷却翻倍；恢复初期杠杆锁1倍
- 10/10 用例通过；decision 冷却中强制观望，sim_account 收盘后自动推进状态

## 待办缺陷（未实施）

### G6. 无资金面维度
- 现状：只用新闻情绪+涨跌幅
- 参照：astock-watch 主力资金流评分（阶段3可选）

### G7. 报告无交互图表
- 现状：纯表格 HTML
- 参照：astock-watch Plotly.js 交互 K 线（低优先级）

### G8. 无技术指标与K线形态识别 → 已实施（2026-08-13）
**来源**：对照 InStock（myhhub/stock，13.8k stars）——它内置 32 种技术指标（MACD/KDJ/RSI/BOLL 等，基于 talib）与 61 种 K 线形态识别，作为综合选股的技术面依据。
- 现状：NewsPulse 决策仅依赖新闻情绪分 + 单日涨跌幅，无趋势/动量/超买超卖维度
- 潜在价值：为决策增加技术面辅助因子（如情绪利好 + MACD 金叉共振才买），弥补新闻滞后

**已实施（2026-08-13，方案：纯 pandas + 辅助因子不改主规则）**：
- `src/indicators.py` 新建：MA(5/20/60)/MACD/KDJ/RSI/BOLL 五指标，纯 pandas 无 talib 依赖；`analyze()` 汇总状态（均线多头/金叉/超买超卖/布林突破），`describe()` 生成可读摘要；数据不足返回 `ok=False`，宁缺毋假
- `src/kline_patterns.py` 新建：8 种高频形态识别（早晨之星/黄昏之星/锤头线/上吊线/长阳吞没/十字星/射击之星/乌云盖顶），锤头/上吊按涨跌背景区分
- `src/decision.py` 集成：作为辅助因子——仅均线多头共振时 confidence +0.1，reason 追加技术摘要与形态，**不改变买卖主规则/杠杆/熔断**（用户确认方案）
- 测试：tests/test_indicators.py 16 用例（恒定序列/超买构造/形态识别/边界），全绿；修复 RSI 除零缺陷（纯上涨应=100 而非 NaN→50）
- 回归：48/48 用例通过；全链路 run_all 正常（信号仍全 hold，主规则无变化）；回测结果与实施前一致
- 预留：talib 升级、形态扩展 61 种留待后续

## 结论

三项核心缺陷已闭环修复，系统从"能跑"升级为"可验证"：
- 情绪分类正确性 ↑（否定/程度处理）
- 策略可评估（预测校验闭环，学习型系统灵魂）
- 数据可信度 ↑（宁缺毋假，无隐式编造）
