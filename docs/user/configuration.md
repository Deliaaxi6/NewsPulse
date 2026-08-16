# Configuration — 配置说明

> 所有可调参数集中在 `config.py`。改配置无需重启（下次运行生效）。密钥在服务器 `secrets.json`。

## 股票池

```python
STOCKS = [
    {"code": "600519.XSHG", "name": "贵州茅台"},
    {"code": "000858.XSHE", "name": "五粮液"},
    {"code": "601318.XSHG", "name": "中国平安"},
    {"code": "600036.XSHG", "name": "招商银行"},
]
```

> 格式注意：akshare 使用 `600519.XSHG`（上海）与 `000858.XSHE`（深圳）格式。

## 关键词（filter_news.py）

`config.py` 中维护三组关键词，命中即归类：

```python
KEYWORDS_BULL  = ["利好", "增长", "突破", "中标", "回购", "增持", "超预期", "涨价", "获批", "盈利预增"]
KEYWORDS_BEAR  = ["利空", "下滑", "亏损", "减持", "处罚", "违规", "立案", "诉讼", "下调", "爆雷"]
KEYWORDS_NEUT  = ["澄清", "回应", "说明", "例行", "公告"]
```

情绪分计算：`(利好条数 - 利空条数) / 总条数`，映射到 [-1, 1]。可随时增删关键词。

## 交易与杠杆参数

| 参数 | 默认 | 含义 |
|---|---|---|
| `INIT_CASH` | 100000 | 模拟初始资金 |
| `SENTI_BUY_THRESHOLD` | 0.3 | 高于此情绪分才考虑买入 |
| `SENTI_SELL_THRESHOLD` | -0.3 | 低于此情绪分卖出 |
| `LEVERAGE_HIGH` | 3 | 情绪 ≥0.6 时杠杆 |
| `LEVERAGE_MID` | 2 | 情绪 0.3~0.6 时杠杆 |
| `LEVERAGE_LOW` | 1 | 默认杠杆 |
| `MAX_POSITION_RATIO` | 0.30 | 单只股票仓位上限 |
| `MAX_TOTAL_RATIO` | 0.90 | 总仓位上限 |
| `COMMISSION_RATE` | 0.00025 | 佣金率（万2.5） |
| `STAMP_TAX` | 0.0005 | 印花税（卖出） |
| `MIN_COMMISSION` | 5 | 最低佣金（元） |

## 熔断参数（安全阀，谨慎修改）

| 参数 | 默认 | 含义 |
|---|---|---|
| `CIRCUIT_TRIGGER_RATIO` | 0.33 | 3倍杠杆下总市值跌超33%触发熔断 |
| `COOLDOWN_DAYS` | 5 | 冷却期（交易日） |
| `RECOVERY_SENTI_DAYS` | 2 | 恢复需连续情绪转正日数 |
| `RECOVERY_LEVERAGE_CAP` | 1 | 恢复初期杠杆上限 |
| `REPEAT_PENALTY_MULTIPLIER` | 2 | 两周内二次熔断冷却翻倍 |

## 数据与日志路径

| 配置 | 默认（Linux 部署） | 本地开发 |
|---|---|---|
| `DATA_DIR` | /opt/newsquant/data | ./data |
| `REPORTS_DIR` | /opt/newsquant/reports | ./reports |
| `LOGS_DIR` | /opt/newsquant/logs | ./logs |

路径随 `sys.platform` 或显式配置切换，代码内禁止硬编码路径。

## 密钥文件 secrets.json（服务器）

```json
{
  "NEWSPULSE_TG_SCRIPT": "/opt/newspulse/tools/send_telegram.py",
  "NEWSPULSE_TG_CONFIG": "/opt/newspulse/secrets/tg_config.json",
  "TG_PROXY": "http://127.0.0.1:7897"
}
```

- 权限 `chmod 600`，不进 git（`.gitignore` 已排除）
- Bot Token / chat_id 放 `tg_config.json`（复用 `send_telegram.py --config` 指定）
- 修改后无需重启，下次运行自动生效