# Knowledge — akshare 接口速查（外部集成）

> akshare 是免费开源财经数据接口库。接口细节可能随版本变化，使用前以实际返回为准。
> 容错策略见 ARCHITECTURE.md 第6节（重试→备用接口→缺失标记）。

## 安装与版本

```bash
pip install akshare
# 建议锁定 requirements.txt: akshare>=1.14
```

## 本系统用到的接口

### 新闻类

| 需求 | 接口名 | 说明 |
|---|---|---|
| 大盘财经快讯 | `ak.stock_info_global_em()` | 东方财富全球财经快讯，返回 `标题/内容/发布时间/相关股票` |
| 个股新闻 | `ak.stock_news_em(symbol="600519")` | 东方财富个股新闻（symbol 不带后缀） |
| 备用新闻源 | `ak.stock_info_global_cls()` | 财联社电报（备用） |

### 行情类

| 需求 | 接口名 | 说明 |
|---|---|---|
| 实时行情 | `ak.stock_zh_a_spot_em()` | 全A股实时快照（含涨跌幅），按代码过滤 |
| 历史K线 | `ak.stock_zh_a_hist(symbol="600519", period="daily", start_date=..., end_date=...)` | 用于 MA5/MA20 死叉判断 |
| 备用行情 | `ak.stock_zh_a_daily(symbol="sh600519")` | 新浪历史行情（备用） |

## 代码格式约定（关键坑）

| 场景 | 格式 | 示例 |
|---|---|---|
| 股票池配置 | `XXXXXX.XSHG/.XSHE` | 600519.XSHG（沪）、000858.XSHE（深） |
| `stock_news_em` / `stock_zh_a_hist` | 6位纯数字 | "600519" |
| `stock_zh_a_daily`（新浪） | 带前缀 | "sh600519" / "sz000858" |

> ⚠️ 各接口对代码格式要求不同，转换逻辑统一放 `config.py` 或 `fetch` 工具函数，勿散落各模块。

## 返回列名参考（可能变化）

- `stock_info_global_em` 返回：`发布时间, 标题, 内容, 相关股票, 点击量`（可能略有差异，抓取时按列名可空容忍处理）
- `stock_zh_a_spot_em` 返回：`代码, 名称, 最新价, 涨跌幅, ...`（字段极多，只需 `代码/名称/最新价/涨跌幅`）

## 字段容错策略

- 列不存在 → 返回空 DataFrame → 走"数据缺失"分支
- 中文编码 → pandas 默认 utf-8 读取，写入 CSV 指定 `encoding="utf-8-sig"`（Excel 兼容）
- 接口变慢 → 单接口超时 30s 上限，全部接口总耗时控制在 3 分钟内（1核2G 限制）