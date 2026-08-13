# ARCHITECTURE — 技术参考

> 面向 AI 协作者与未来的你：模块间数据契约、关键技术实现、测试策略。编码时以此为准。

## 1. 模块管线与数据契约

```
run_all.py (入口)
   │
   ├─ ① fetch_news.py ──→ data/news_{date}.csv
   │       cols: time,title,content,source,related_stocks,senti
   │
   ├─ ② filter_news.py ──→ data/daily_sentiment.csv
   │       cols: date,senti_score,total_news,pos_cnt,neg_cnt,neutral_cnt
   │       输入: news_{date}.csv
   │
   ├─ ③ decision.py ──→ data/decision_{date}.csv
   │       cols: date,stock,signal,leverage,reason
   │       输入: daily_sentiment.csv + 当日行情(akshare) + portfolio.csv
   │
   ├─ ④ sim_account.py ──→ data/portfolio.csv + data/trade_log.csv
   │       portfolio: date,stock,shares,cost,market_value,cash,leverage,total_value
   │       trade_log: date,stock,action,price,shares,amount,leverage,reason
   │       输入: decision_{date}.csv + 次日开盘价
   │
   └─ ⑤ daily_report.py ──→ reports/report_{date}.html + 邮件推送
           输入: 当日全部 CSV
```

### 契约要点
- 每模块独立可运行（`--date` 参数），单测友好
- 模块间通过 CSV 文件解耦，不跨模块 import（config.py 除外）
- 所有日期用 `YYYY-MM-DD`

## 2. 决策规则引擎

```
输入: senti_score ∈ [-1,1]（当日全池新闻情绪分）
      stock_change = 个股当日涨跌幅

买入条件: senti_score > +0.3 AND stock_change > 0
卖出条件: senti_score < -0.3 OR 均线死叉(MA5<MA20且前日MA5≥MA20)
观望:     其余

杠杆映射:
  senti_score ≥ +0.6 → 3倍
  +0.3 ≤ senti_score < +0.6 → 2倍
  senti_score < +0.3 → 1倍
```

## 3. 模拟撮合引擎

- 成交价：信号次日开盘价（akshare 获取）
- T+1：当日买入不可当日卖出（用 trade_log 校验）
- 费用：佣金 = max(金额×0.00025, 5元)；印花税 = 卖出金额×0.0005
- 仓位限制：单票 ≤30% 总资产；总仓 ≤90%；剩余为现金
- 停牌处理：行情获取失败 → 跳过该股当日（日志记录），不影响其他
- 涨停不卖/跌停不买：按当日涨跌幅判断（±10%，ST 为 ±5%）

## 4. 熔断器（核心安全阀）

```
触发: 杠杆=3 且 总市值(含杠杆)较建仓成本 跌超33%
动作: 全部清仓 → 邮件告警 → state.json 记为 cooling(start_date)
恢复: 冷却期 ≥5 交易日 且 最近连续2日 senti_score>0
      → 恢复交易，但杠杆上限锁定为 1 倍（直到连续盈利 10 日才放开）
防循环: 恢复后若两周内再次熔断 → 冷却期翻倍（10日）并触发人工警告邮件
```

实现：`data/state.json` 持久化熔断状态，防止重启丢失。

## 5. 邮件通知

- 复用 `C:\Users\Delia\.cc-switch\skills\email-notification\scripts\send_email.py`
- 服务器部署时复制该脚本到项目 `tools/` 目录
- SMTP 凭据：`secrets.json`（chmod 600），**禁止进 git**
- 失败不阻塞主流程（日志记录即可，对应规则19）

## 6. 重试与降级策略

```
akshare 主接口失败 → 重试3次（5s/15s/30s）→ 备用接口（新浪）
两次均失败 → 当日该数据源标记缺失，走"数据缺失"分支，邮件通知
```

## 7. 配置

- `config.py`：纯配置（股票池/阈值/费率/路径），不含密钥
- `secrets.json`：密钥（服务器专属，本地开发用测试账号或留空跳过邮件）
- 路径统一由 config.py 管理（Windows 本地 vs Linux 服务器差异）

## 8. 测试策略（阶段1：日志断言 + 单元测试）

| 测试对象 | 方法 |
|---|---|
| filter_news 情绪分类 | 构造已知情绪的新闻样本，断言分类正确；含边界（空文本/夹杂数字） |
| decision 信号 | 断言阈值边界（0.3 恰等/负值/极端） |
| sim_account 费用 | 断言最低佣金5元、印花税计算 |
| sim_account T+1 | 断言当日买入不可卖 |
| 熔断器 | 断言33%触发、冷却期不交易、恢复条件 |
| 空数据/停牌 | 断言跳过不崩溃 |

## 9. 部署拓扑

```
火山云 Linux (1核2G)
├── /opt/newsquant/           # 部署目录
│   ├── src/  tools/  data/  reports/  logs/
│   ├── secrets.json (600)
│   └── requirements.txt
├── crontab 16:30 工作日: bash /opt/newsquant/run_all.sh
└── ~/.ssh 密钥认证（禁止密码登录）
```