"""NewsPulse 配置模块（demo 版）。密钥不进本文件。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
for d in (DATA_DIR, REPORTS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 邮件推送（复用 send_email.py，密钥在其 config.json，不进 git / 不硬编码）
EMAIL_SCRIPT = os.environ.get(
    "NEWSPULSE_EMAIL_SCRIPT",
    r"C:\Users\Delia\.cc-switch\skills\email-notification\scripts\send_email.py")
EMAIL_CONFIG = os.environ.get("NEWSPULSE_EMAIL_CONFIG", "")  # 服务器部署时指定 secrets/email_config.json
EMAIL_TO = os.environ.get("NEWSPULSE_EMAIL_TO", "228396705@qq.com")
EMAIL_CC = os.environ.get("NEWSPULSE_EMAIL_CC", "deliaaxi6@gmail.com")

# Telegram 推送（Phase 3）：token/chat_id 从环境变量读取（服务器 secrets.json 注入），
# 不硬编码不进 git；未配置则跳过推送（fail-open）。走本地代理出墙（默认 Clash 7897）。
TELEGRAM_BOT_TOKEN = os.environ.get("NEWSPULSE_TG_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("NEWSPULSE_TG_CHAT_ID", "")
TELEGRAM_API_BASE = os.environ.get("NEWSPULSE_TG_API", "https://api.telegram.org")
TELEGRAM_PROXY = os.environ.get("NEWSPULSE_TG_PROXY", "http://127.0.0.1:7897")

# DeepSeek LLM 新闻分类（Phase 3）：key 从环境变量读取（不硬编码不进 git），
# 未配置则跳过 LLM 分类（降级关键词规则）；api.deepseek.com 国内直连无需代理。
DEEPSEEK_API_KEY = os.environ.get("NEWSPULSE_DS_KEY", "")
DEEPSEEK_MODEL = os.environ.get("NEWSPULSE_DS_MODEL", "deepseek-v4-flash")
DEEPSEEK_API = os.environ.get("NEWSPULSE_DS_API", "https://api.deepseek.com")

# 回测基准池（backtest.py 专用）：生产链路观察池已切换为 select_stock 动态选股
# （data/select_YYYY-MM-DD.csv，涨停池+策略模板），不再从本常量取每日标的。
STOCKS = [
    {"code": "600519.XSHG", "symbol": "600519", "name": "贵州茅台"},
    {"code": "000858.XSHE", "symbol": "000858", "name": "五粮液"},
    {"code": "601318.XSHG", "symbol": "601318", "name": "中国平安"},
    {"code": "600036.XSHG", "symbol": "600036", "name": "招商银行"},
]

KEYWORDS_BULL = ["利好", "增长", "突破", "中标", "回购", "增持", "超预期", "涨价", "获批", "盈利预增", "上调", "创纪录", "创新高"]
KEYWORDS_BEAR = ["利空", "下滑", "亏损", "减持", "处罚", "违规", "立案", "诉讼", "下调", "爆雷", "预警", "不及预期", "低于预期", "亏损扩大", "市值缩水", "未达预期", "造假", "传闻"]
KEYWORDS_NEUT = ["澄清", "回应", "说明", "例行", "公告", "提示"]
# 通用否定词：可翻转任意方向（"未能增长"→利空、"否认造假"→利好）
# 注：不及/低于/未达 已作为复合负面词（不及预期/低于预期/未达预期）直接入库，
#     不再参与翻转，避免"业绩未达预期"这类独立负面句被窗口误翻。
NEGATION_GENERAL = ["未能", "否认", "没有", "未见"]
# 削弱利好词：只翻转 bull（"增长放缓"→利空），不翻转 bear（"亏损承压"仍是利空）
NEGATION_BULL_ONLY = ["放缓", "减弱", "趋缓", "承压", "受阻", "拖累", "乏力"]
INTENSIFY_STRONG = ["大幅", "显著", "强劲", "快速", "明显", "爆发", "迅猛", "倍增", "翻倍", "激增", "创历史"]
INTENSIFY_WEAK = ["小幅", "略", "微", "轻微", "温和", "缓慢", "有限"]

INIT_CASH = 100000.0
SENTI_BUY_THRESHOLD = 0.3
SENTI_SELL_THRESHOLD = -0.3
LEVERAGE_HIGH = 3
LEVERAGE_MID = 2
LEVERAGE_LOW = 1
MAX_POSITION_RATIO = 0.30
MAX_TOTAL_RATIO = 0.90
COMMISSION_RATE = 0.00025
STAMP_TAX = 0.0005
MIN_COMMISSION = 5.0

SENTI_SCORE_CUT = 0.6

LIMIT_UP_PCT = 9.9
LIMIT_DOWN_PCT = -9.9
ONE_WORD_TOL = 0.01
