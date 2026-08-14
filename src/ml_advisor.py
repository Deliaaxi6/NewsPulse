"""ML 联合决策框架（Phase 3）：逻辑回归预测次日账户下跌概率，作为辅助因子微调 confidence。

- 纯 numpy 实现（不引入 sklearn 依赖；规则：不擅自装包）
- 数据 < MIN_SAMPLES（20 交易日）→ 自动跳过（enabled=False，决策链路不受影响）
- 特征（仅用本地 CSV，无网络依赖）：senti_score / senti_mom（情绪一阶差分）/ bull_ratio
  （利好占比）/ total_news / senti_ma3（3 日情绪均值）
- 标签：次日总资产下跌=1 / 不跌=0（portfolio.csv 每日 total_value）
- 输出 advice：{"enabled", "p_drop", "intervene", "penalty"}；所有异常 fail-open 返回 enabled=False
- 干预规则：p_drop ≥ INTERVENE_THRESHOLD → confidence -CONF_PENALTY（不改买卖主规则/杠杆/熔断）
"""
import datetime as dt

import numpy as np
import pandas as pd

from config import DATA_DIR

MIN_SAMPLES = 20
L2 = 1e-3
LR = 0.1
EPOCHS = 2000
INTERVENE_THRESHOLD = 0.6
CONF_PENALTY = 0.1

_cache = {"trained": None, "date": None}  # 模块级训练缓存（同日只训一次）


def _features(df: pd.DataFrame) -> np.ndarray:
    s = df["senti_score"].astype(float).values
    total = df["total_news"].astype(float).values
    pos = df["pos_cnt"].astype(float).values
    neg = df["neg_cnt"].astype(float).values
    denom = pos + neg
    bull_ratio = np.where(denom > 0, pos / np.maximum(denom, 1), 0.5)
    ma3 = pd.Series(s).rolling(3, min_periods=1).mean().values
    mom = np.concatenate([[0.0], np.diff(s)])
    return np.column_stack([s, mom, bull_ratio, total, ma3])


def _labels(tv_by_date: pd.Series, dates) -> list:
    """dates 对应的次日标签：次日 total_value 低于当日 → 1，无次日 → None。"""
    tv_by_date = tv_by_date.sort_index()
    out = []
    for d in dates:
        d = pd.Timestamp(d)
        prev = tv_by_date[tv_by_date.index <= d]
        nxt = tv_by_date[tv_by_date.index > d]
        if len(prev) == 0 or len(nxt) == 0:
            out.append(None)
        else:
            out.append(1 if nxt.iloc[0] < prev.iloc[-1] else 0)
    return out


class _LogReg:
    def __init__(self):
        self.w = None
        self.b = 0.0
        self.mu = None
        self.sd = None

    def _std(self, X):
        if self.mu is None:
            self.mu = X.mean(axis=0)
            self.sd = X.std(axis=0) + 1e-9
        return (X - self.mu) / self.sd

    def fit(self, X, y):
        Xs = self._std(X)
        n, d = Xs.shape
        w = np.zeros(d)
        b = 0.0
        for _ in range(EPOCHS):
            z = Xs @ w + b
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            grad_w = Xs.T @ (p - y) / n + L2 * w
            grad_b = (p - y).mean()
            w -= LR * grad_w
            b -= LR * grad_b
        self.w, self.b = w, b

    def predict_proba(self, X):
        if self.w is None:
            return 0.5
        z = self._std(X) @ self.w + self.b
        return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _train() -> dict | None:
    """训练；数据不足/异常返回 None。"""
    sp = DATA_DIR / "daily_sentiment.csv"
    pf = DATA_DIR / "portfolio.csv"
    if not sp.exists() or not pf.exists():
        return None
    df = pd.read_csv(sp, encoding="utf-8-sig")
    portfolio = pd.read_csv(pf, encoding="utf-8-sig")
    if len(df) < MIN_SAMPLES:
        return None
    tv = portfolio.groupby("date")["total_value"].last()
    tv.index = pd.to_datetime(tv.index)
    X = _features(df)
    y = np.array([v for v in _labels(tv, df["date"]) if v is not None])
    rows = np.array([v is not None for v in _labels(tv, df["date"])])
    if len(y) < MIN_SAMPLES * 0.5 or len(np.unique(y)) < 2:
        return None
    X = X[rows]
    model = _LogReg()
    model.fit(X, y)
    return {"model": model, "last": X[-1]}


def advice(date_str: str | None = None) -> dict:
    """返回次日下跌概率与干预建议；未启用/异常 → {"enabled": False}。"""
    try:
        if _cache["trained"] is None or _cache["date"] != date_str:
            _cache["trained"] = _train()
            _cache["date"] = date_str
        if _cache["trained"] is None:
            return {"enabled": False}
        model = _cache["trained"]["model"]
        p = float(model.predict_proba(_cache["trained"]["last"].reshape(1, -1))[0])
        out = {"enabled": True, "p_drop": round(p, 4)}
        if p >= INTERVENE_THRESHOLD:
            out["intervene"] = True
            out["penalty"] = CONF_PENALTY
            out["reason"] = f"ML风控: 次日下跌概率{p:.0%}"
        else:
            out["intervene"] = False
        return out
    except Exception as e:
        print(f"[warn] ML 风控异常(fail-open): {e}")
        return {"enabled": False}


def main(date_str=None):
    date_str = date_str or dt.date.today().isoformat()
    a = advice(date_str)
    if not a["enabled"]:
        print(f"[info] ML 风控未启用（需 ≥{MIN_SAMPLES} 个交易日样本，当前不足）")
        return
    print(f"[ok] ML 风控: 次日下跌概率 {a['p_drop']:.1%}"
          + (f" → 干预降confidence {a['penalty']}" if a["intervene"] else " → 不干预"))


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    date_str = None
    if args:
        if args[0] == "--date" and len(args) > 1:
            date_str = args[1]
        else:
            date_str = args[0]
    main(date_str)