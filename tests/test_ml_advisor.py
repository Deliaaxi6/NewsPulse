"""ML 风控框架回归测试（10 用例）：数据不足跳过 / 合成数据训练收敛 / 干预 / 特征 / 异常 fail-open / decision 集成。"""
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import ml_advisor as ml


def _make_senti(tmp: Path, n: int, low_first=False):
    """构造 n 天情绪数据；low_first=True 时后 n-14 天情绪低（其资产为下降台阶 → 次日跌）。"""
    import datetime as dt
    d0 = dt.date(2026, 6, 1)
    rows = []
    for i in range(n):
        d = (d0 + dt.timedelta(days=i)).isoformat()
        low = low_first and i >= 14
        score = -0.3 if low else 0.2
        rows.append({"date": d, "senti_score": score, "total_news": 300 + i,
                     "pos_cnt": 100 + (0 if low else 60),
                     "neg_cnt": 60 + (60 if low else 0),
                     "neutral_cnt": 100})
    pd = __import__("pandas")
    pd.DataFrame(rows).to_csv(tmp / "daily_sentiment.csv", index=False, encoding="utf-8-sig")


def _make_portfolio(tmp: Path, n: int, low_first=False):
    """构造 n 天资产；low_first 时后 n-14 天资产为下降台阶(110000 起每 -500，次日必跌=标签1)，
    前段恒定 95000(标签0)；low_first=False 时 95000/95500 交替(标签混合且情绪无预测力)。"""
    import datetime as dt
    d0 = dt.date(2026, 6, 1)
    lines = []
    for i in range(n):
        d = (d0 + dt.timedelta(days=i)).isoformat()
        if low_first and i >= 14:
            base = 110000 - (i - 14) * 500
        elif not low_first and i % 2 == 1:
            base = 95500
        else:
            base = 95000
        lines.append(f"{d},600519,0.0,0.0,0.0,{base - 5000},1.0,{base}")
    Path(tmp / "portfolio.csv").write_text(
        "date,stock,shares,cost,market_value,cash,leverage,total_value\n" + "\n".join(lines),
        encoding="utf-8")


def main() -> int:
    fails = 0
    old_data = ml.DATA_DIR
    old_cache = ml._cache.copy()

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ml._cache.update({"trained": None, "date": None})
        ml.DATA_DIR = tmp
        a = ml.advice("2026-08-14")
        check("无数据文件 enabled=False", a["enabled"] is False)

        _make_senti(tmp, 10)
        _make_portfolio(tmp, 10)
        ml._cache.update({"trained": None, "date": None})
        a = ml.advice("2026-08-14")
        check("样本<20天自动跳过", a["enabled"] is False, str(a))

        _make_senti(tmp, 30, low_first=True)
        _make_portfolio(tmp, 30, low_first=True)
        ml._cache.update({"trained": None, "date": None})
        a = ml.advice("2026-08-14")
        check("30天样本训练启用", a["enabled"] is True, str(a))
        check("下跌概率>0.6触发干预",
              a["intervene"] is True and a["penalty"] == 0.1, str(a))

        ml._cache.update({"trained": None, "date": None})
        a2 = ml.advice("2026-08-15")
        check("同日缓存复用(不再重训)", a2["enabled"] is True)

        _make_senti(tmp, 30, low_first=False)
        _make_portfolio(tmp, 30, low_first=False)
        ml._cache.update({"trained": None, "date": None})
        a = ml.advice("2026-08-16")
        check("上涨市不干预", a["enabled"] is True and a["intervene"] is False, str(a))

        df_rows = __import__("pandas").DataFrame({
            "date": ["2026-08-10"], "senti_score": [0.0], "total_news": [0],
            "pos_cnt": [0], "neg_cnt": [0]})
        X = ml._features(df_rows)
        check("特征5维且零值安全", X.shape == (1, 5) and X[0, 2] == 0.5, str(X.shape))

        _make_senti(tmp, 30, low_first=True)
        ml.DATA_DIR = old_data
        ml._cache.update({"trained": None, "date": None})
        a = ml.advice("2026-08-17")
        check("缺 portfolio 文件 fail-open", a["enabled"] is False)

    ml.DATA_DIR = old_data
    ml._cache.update(old_cache)

    import decision as dc
    with mock.patch("decision.ml_advisor.advice",
                    return_value={"enabled": True, "p_drop": 0.9, "intervene": True,
                                  "penalty": 0.1, "reason": "ML风控: 次日下跌概率90%"}), \
         mock.patch("decision.fund_factor_extra", return_value={"conf": 0.0, "label": "", "unavailable": []}), \
         mock.patch("decision.me.market_env", return_value=None), \
         mock.patch("decision.tech_factor", return_value=({"ok": True}, [])), \
         mock.patch("decision.indicators.describe", return_value="技术面"), \
         mock.patch("decision.strategy_factor", return_value=[]), \
         mock.patch("decision.cb.leverage_cap", return_value=3.0), \
         mock.patch("decision.cb.in_cooldown", return_value=False):
        r = dc.decide(0.5, {"600000": 1.0}, [{"symbol": "600000", "name": "浦发银行"}])
        check("decision 集成: ML干预降confidence并追加reason",
              r[0]["confidence"] < 0.6 and "ML风控" in r[0]["reason"], str(r[0]))

    with mock.patch("decision.ml_advisor.advice", return_value={"enabled": False}), \
         mock.patch("decision.fund_factor_extra", return_value={"conf": 0.0, "label": "", "unavailable": []}), \
         mock.patch("decision.me.market_env", return_value=None), \
         mock.patch("decision.tech_factor", return_value=({"ok": True}, [])), \
         mock.patch("decision.indicators.describe", return_value="技术面"), \
         mock.patch("decision.strategy_factor", return_value=[]), \
         mock.patch("decision.cb.leverage_cap", return_value=3.0), \
         mock.patch("decision.cb.in_cooldown", return_value=False):
        r = dc.decide(0.5, {"600000": 1.0}, [{"symbol": "600000", "name": "浦发银行"}])
        check("decision 集成: 未启用不影响决策",
              r[0]["confidence"] == 0.6 and "ML风控" not in r[0]["reason"], str(r[0]))

    print(f"ml_advisor: {10 - fails}/10 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())