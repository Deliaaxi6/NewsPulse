"""综合选股测试（InStock 融入）：涨停池→策略扫描→观察池 CSV 的确定性用例。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pandas as pd

import select_stock
from config import DATA_DIR

TEST_DATE = "2099-01-01"


def main() -> int:
    fails = 0

    def check(name, cond, note=""):
        nonlocal fails
        fails += 0 if cond else 1
        print(f"[{'OK' if cond else 'FAIL'}] {name} {note}")

    out = DATA_DIR / f"select_{TEST_DATE}.csv"
    if out.exists():
        out.unlink()
    select_stock.fund_flow.is_trading_day = lambda d: True
    orig_pool, orig_detect = select_stock._zt_pool, select_stock.strategies.detect
    orig_market = select_stock._market_pool
    orig_notify = select_stock.alert.notify
    notified = []
    select_stock.alert.notify = lambda *a, **k: notified.append((a, k)) or False
    select_stock._market_pool = lambda d: []  # 测试禁用全市场快照网络调用

    # --- 方案C：全市场快照本地过滤（纯函数） ---
    snap = pd.DataFrame([
        {"代码": "600001", "名称": "正常股", "涨跌幅": 3.2, "量比": 2.5, "成交额": 5e8},
        {"代码": "600002", "名称": "*ST 退市股", "涨跌幅": 3.2, "量比": 2.5, "成交额": 5e8},
        {"代码": "600003", "名称": "涨停股", "涨跌幅": 10.0, "量比": 2.5, "成交额": 5e8},
        {"代码": "600004", "名称": "下跌股", "涨跌幅": -1.0, "量比": 2.5, "成交额": 5e8},
        {"代码": "600005", "名称": "低量比", "涨跌幅": 3.2, "量比": 1.2, "成交额": 5e8},
        {"代码": "600006", "名称": "低成交额", "涨跌幅": 3.2, "量比": 2.5, "成交额": 1e8},
        {"代码": "600007", "名称": "正常股2", "涨跌幅": 0.5, "量比": 2.0, "成交额": 3e8},
    ])
    f = select_stock._filter_market_df(snap)
    check("快照过滤 保留正常股", set(f["代码"]) == {"600001", "600007"}, str(set(f["代码"])))
    check("快照过滤 空df", select_stock._filter_market_df(pd.DataFrame()).empty)
    check("快照过滤 None", select_stock._filter_market_df(None).empty)
    check("快照过滤 缺列容错", len(select_stock._filter_market_df(pd.DataFrame(
        [{"代码": "600001", "名称": "正常股"}]))) == 1)

    # --- 新浪快照降级源：列转换（mock 分页请求） ---
    import json as _json

    class FakeResp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    pages = [
        [{"symbol": "sh600001", "name": "甲股", "changepercent": "3.2",
          "amount": "50000", "volume_ratio": "2.5"},
         {"symbol": "sz000002", "name": "乙股", "changepercent": "2.1",
          "amount": "30000"}],
        [{"symbol": "sz000003", "name": "丙股", "changepercent": "1.0",
          "amount": "20000", "volume_ratio": "1.8"}],
    ]
    import select_stock as _ss
    _orig_get = _ss.requests.get

    def fake_get(url, params, timeout):
        return FakeResp(_json.dumps(pages[params["page"] - 1] if params["page"] <= len(pages) else []))

    _ss.requests.get = fake_get
    snap_sina = _ss._sina_spot()
    check("新浪 代码截取", list(snap_sina["代码"]) == ["600001", "000002", "000003"])
    check("新浪 成交额万元转元", snap_sina.iloc[0]["成交额"] == 5e8)
    check("新浪 缺量比填NaN", pd.isna(snap_sina.iloc[1]["量比"]))
    check("新浪 过滤（NaN量比通过）", set(_ss._filter_market_df(snap_sina)["代码"]) == {"600001", "000002"})
    fake_get_empty = lambda url, params, timeout: FakeResp("[]")
    _ss.requests.get = fake_get_empty
    try:
        _ss._sina_spot()
        check("新浪 全空页抛异常", False)
    except ValueError:
        check("新浪 全空页抛异常", True)

    # --- 早盘 0 值校验（宁缺毋假）：任一列 0 值占比>95% → 源不可用 ---
    def check_zero(name, df, expect_raise):
        try:
            _ss._validate_snapshot(df)
            check(name, not expect_raise)
        except ValueError:
            check(name, expect_raise)

    zero_pct = pd.DataFrame([
        {"代码": "600001", "名称": "甲", "涨跌幅": 0.0, "量比": 0.0, "成交额": 0.0},
        {"代码": "600002", "名称": "乙", "涨跌幅": 0.0, "量比": 0.0, "成交额": 0.0},
    ])
    check_zero("早盘0值 三列全0抛异常", zero_pct, True)
    pct_zero = zero_pct.copy()
    pct_zero["成交额"] = [5e8, 3e8]
    check_zero("早盘0值 仅涨跌幅全0抛异常", pct_zero, True)
    vol_zero = zero_pct.copy()
    vol_zero["涨跌幅"] = [3.2, 2.1]
    check_zero("早盘0值 仅量比全0抛异常", vol_zero, True)
    amt_zero = zero_pct.copy()
    amt_zero["涨跌幅"] = [3.2, 2.1]
    amt_zero["量比"] = [2.5, 2.0]
    check_zero("早盘0值 仅成交额全0抛异常", amt_zero, True)
    normal_snap = pd.DataFrame([
        {"代码": "600001", "名称": "甲", "涨跌幅": 3.2, "量比": 2.5, "成交额": 5e8},
        {"代码": "600002", "名称": "乙", "涨跌幅": 0.0, "量比": 0.0, "成交额": 0.0},
    ])
    check_zero("早盘0值 个别股0值放行", normal_snap, False)
    check_zero("早盘0值 空表放行", pd.DataFrame(), False)
    check_zero("早盘0值 缺列放行", pd.DataFrame([{"代码": "600001"}]), False)
    nan_all = pd.DataFrame([{"代码": "600001", "涨跌幅": None, "量比": None, "成交额": None}])
    check_zero("早盘0值 全NaN放行", nan_all, False)
    check("早盘0值 校验后正常数据原样返回",
          len(_ss._validate_snapshot(normal_snap)) == 2)

    zero_pages = [[{"symbol": "sh600001", "name": "甲", "changepercent": "0.00", "amount": "0"},
                   {"symbol": "sz000002", "name": "乙", "changepercent": "0.00", "amount": "0"}]]
    _ss.requests.get = lambda url, params, timeout: FakeResp(
        _json.dumps(zero_pages[params["page"] - 1] if params["page"] <= len(zero_pages) else []))
    try:
        _ss._sina_spot()
        check("新浪 早盘全0快照抛异常", False)
    except ValueError:
        check("新浪 早盘全0快照抛异常", True)
    em_zero_payload = {"data": {"diff": [
        {"f12": "600001", "f14": "甲", "f3": 0.0, "f10": 0.0, "f6": 0.0},
        {"f12": "000002", "f14": "乙", "f3": 0.0, "f10": 0.0, "f6": 0.0},
    ], "total": 2}}
    _ss.requests.get = lambda url, params, timeout: FakeResp(_json.dumps(em_zero_payload))
    try:
        _ss._em_spot_alt(("83.push2",))
        check("em_alt 早盘全0抛异常", False)
    except ValueError:
        check("em_alt 早盘全0抛异常", True)
    _ss.requests.get = _orig_get

    # --- 东财备用子域：clist JSON → 东财列结构（mock 翻页 + 子域轮换） ---
    em_payload = {"data": {"diff": [
        {"f12": "600001", "f14": "甲股", "f3": 3.2, "f10": 2.5, "f6": 5e8},
        {"f12": "000002", "f14": "乙股", "f3": 2.1, "f10": 1.2, "f6": 3e8},
        {"f12": "600003", "f14": "*ST退", "f3": 3.0, "f10": 2.0, "f6": 4e8},
    ], "total": 3}}
    calls = []

    def fake_em_get(url, params, timeout):
        calls.append((url, params["pn"], params["fid"]))
        if params["pn"] >= 2:
            return FakeResp(_json.dumps({"data": {"diff": [], "total": 3}}))
        return FakeResp(_json.dumps(em_payload))

    _ss.requests.get = fake_em_get
    snap_em = _ss._em_spot_alt(("83.push2", "push2delay"))
    check("备用子域 代码列", list(snap_em["代码"]) == ["600001", "000002", "600003"])
    check("备用子域 成交额原值", snap_em.iloc[0]["成交额"] == 5e8)
    check("备用子域 过滤ST/低量比", set(_ss._filter_market_df(snap_em)["代码"]) == {"600001"})
    check("备用子域 fid=f3请求", calls[0][2] == "f3")

    def fake_em_fail(url, params, timeout):
        if "83.push2" in url:
            raise ConnectionError("bad node")
        calls.append((url, params["pn"], params["fid"]))
        if params["pn"] >= 2:
            return FakeResp(_json.dumps({"data": {"diff": [], "total": 3}}))
        return FakeResp(_json.dumps(em_payload))

    _ss.requests.get = fake_em_fail
    snap_em2 = _ss._em_spot_alt(("83.push2", "push2delay"))
    check("备用子域 页失败换子域重试", len(snap_em2) == 3)
    check("备用子域 换子域计数", any("push2delay" in u for u, p, f in calls))
    _ss.requests.get = lambda url, params, timeout: FakeResp(_json.dumps({"data": {"diff": []}}))
    try:
        _ss._em_spot_alt(("83.push2",))
        check("备用子域 空diff抛异常", False)
    except ValueError:
        check("备用子域 空diff抛异常", True)
    _ss.requests.get = _orig_get

    # --- 方案C：池合并（涨停池优先/去重/排序截断） ---
    zt = [
        {"symbol": "600519", "name": "茅台", "lbc": 2, "seal_amount": 5e8, "source": "zt"},
        {"symbol": "000858", "name": "五粮液", "lbc": 1, "seal_amount": 1e8, "source": "zt"},
    ]
    mk = [
        {"symbol": "000858", "name": "五粮液", "lbc": 0, "seal_amount": 0.0, "source": "market"},
        {"symbol": "601318", "name": "平安", "lbc": 0, "seal_amount": 0.0, "source": "market"},
        {"symbol": "600036", "name": "招行", "lbc": 0, "seal_amount": 0.0, "source": "market"},
    ]
    merged = select_stock._merge_pools(zt, mk)
    check("合并 去重后4只", len(merged) == 4, str([m["symbol"] for m in merged]))
    check("合并 涨停池优先", merged[0]["symbol"] == "600519" and merged[1]["symbol"] == "000858")
    check("合并 保留market股", "601318" in [m["symbol"] for m in merged])
    check("合并 保留source字段", {m["symbol"]: m["source"] for m in merged}["601318"] == "market")

    # --- 正常：3 只涨停池 → 连板降序排序 + detect 命中写入 ---
    pool = pd.DataFrame([
        {"代码": "600519", "名称": "贵州茅台", "连板数": 1, "封板资金": 5e8},
        {"代码": "000858", "名称": "五粮液", "连板数": 3, "封板资金": 1e8},
        {"代码": "601318", "名称": "中国平安", "连板数": 2, "封板资金": 3e8},
    ])
    hits = {"600519": ["海龟突破"], "000858": [], "601318": ["平台突破", "放量上涨"]}
    select_stock._zt_pool = lambda base: pool
    select_stock.strategies.detect = lambda sym: list(hits.get(sym, []))
    select_stock.select(TEST_DATE)
    check("CSV 已写入", out.exists())
    df = pd.read_csv(out, encoding="utf-8-sig", dtype={"symbol": str})
    check("连板数降序", list(df["symbol"]) == ["000858", "601318", "600519"])
    check("code 格式（深）", df.iloc[0]["code"] == "000858.XSHE")
    check("code 格式（沪）", df.iloc[1]["code"] == "601318.XSHG")
    check("code 格式（科创688）", select_stock._code("688836") == "688836.XSHG")
    check("code 格式（创业板300）", select_stock._code("300750") == "300750.XSHE")
    check("code 格式（北交所920）", select_stock._code("920001") == "920001.BJ")
    check("code 格式（北交所833）", select_stock._code("833171") == "833171.BJ")
    check("code 格式（北交所430）", select_stock._code("430047") == "430047.BJ")
    check("未命中 score=0", df.iloc[0]["score"] == 0)
    check("命中策略分号连接", df.iloc[1]["strategies"] == "平台突破;放量上涨" and df.iloc[1]["score"] == 2)
    check("lbc/seal_amount 保留", int(df.iloc[0]["lbc"]) == 3 and float(df.iloc[0]["seal_amount"]) == 1e8)
    rows = select_stock.load_pool(TEST_DATE)
    check("load_pool 读回结构", len(rows) == 3 and rows[0]["symbol"] == "000858")
    check("load_pool 前导0保留", rows[0]["code"] == "000858.XSHE")
    check("load_pool 空策略填空串", rows[0]["strategies"] == "")

    # --- MAX_SCAN 截断 ---
    big = pd.DataFrame([
        {"代码": f"60{i:04d}", "名称": f"股{i}", "连板数": 1, "封板资金": 1e8}
        for i in range(25)
    ])
    select_stock._zt_pool = lambda base: big
    select_stock.strategies.detect = lambda sym: []
    select_stock.select(TEST_DATE)
    df = pd.read_csv(out, encoding="utf-8-sig")
    check("MAX_SCAN 截断", len(df) == 20)

    # --- 涨停池为空 → fail-open 写空 CSV + 告警 ---
    notified.clear()
    select_stock._zt_pool = lambda base: pd.DataFrame()
    select_stock.select(TEST_DATE)
    df = pd.read_csv(out, encoding="utf-8-sig")
    check("空池写空 CSV", df.empty)
    check("空池 load_pool 返回 []", select_stock.load_pool(TEST_DATE) == [])
    check("空池触发降级告警", len(notified) == 1 and "选股池为空" in notified[0][0][0])

    # --- 涨停池接口异常 → fail-open + 告警 ---
    notified.clear()
    select_stock._zt_pool = lambda base: (_ for _ in ()).throw(ConnectionError("boom"))
    select_stock.select(TEST_DATE)
    df = pd.read_csv(out, encoding="utf-8-sig")
    check("接口异常写空 CSV", df.empty)
    check("接口异常触发告警", len(notified) == 1 and "选股池为空" in notified[0][0][0])

    # --- 非交易日 → 不写文件 ---
    select_stock.fund_flow.is_trading_day = lambda d: False
    out.unlink()
    select_stock.select(TEST_DATE)
    check("非交易日跳过不写", not out.exists())

    # --- load_pool 文件不存在 → [] ---
    check("load_pool 缺文件返回 []", select_stock.load_pool("2099-06-06") == [])

    select_stock._zt_pool, select_stock.strategies.detect = orig_pool, orig_detect
    select_stock._market_pool = orig_market
    select_stock.alert.notify = orig_notify
    select_stock.fund_flow.is_trading_day = lambda d: None
    if out.exists():
        out.unlink()
    print("\nselect_stock tests done.")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)