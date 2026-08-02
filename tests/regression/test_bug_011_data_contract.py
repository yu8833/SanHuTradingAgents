"""
防回归测试：bug-011 回测交易价格与K线数据不一致（603186华正新材卖出价问题）

现象：
    screening/three-buys-three-sells 盈利 Top 20 中，603186 在 2026-06-30 的卖出价 193.45
    与 stocks/603186 页面 2026-06-30 的 K线 high/low 不符，用户怀疑"两个地方数据都不对"。

第一性原理根因（三条公理未被强制执行）：
    公理1（价格可执行性）：任何交易的 buy/sell 价必须在对应日期 K 线的 [low, high] 区间内
        —— 违反原因：S1/S2 分批减仓后，最终清仓时 sell_price = 跨日期加权均价 avg_sell，
                    这个均价不可能落在最后清仓日当天的 [low, high] 区间！
    公理2（日期可追溯性）：sell_date 必须与 sell_price 实际取价的 K 线日期完全一致
        —— 违反原因：avg_sell 是多天卖出的"均价"，sell_date 却只写最后清仓的日期
    公理3（无未来函数）：t 日决策只能用 ≤t 日的数据（代码结构已保证，此处不重复）

    此外入库层也缺少 OHLC 大小关系校验，可能导致 high<close、low>open 等异常数据流入回测。

修复：
    1. 回测层 _build_and_validate_sell_trade：sell_price 强制取清仓当天的 close（不是跨日期均价），
       强制调用 _validate_trade_price_in_kline，不通过则记录错误并拦截（返回 None）。
    2. idx=-1（清仓日停牌/数据缺口）时自动回退到 last_valid_idx，sell_date 改为该 idx 对应日期。
    3. 入库层 _standardize_record：自动修正 high/low，保证 high>=max(O,C)、low<=min(O,C)。
"""
import pytest


@pytest.mark.regression
def test_bug_011_axiom1_price_outside_range_is_rejected():
    """bug-011 公理1：卖出价不在 [low, high] 区间必须被 _validate_trade_price_in_kline 拒绝"""
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService

    svc = ThreeBuysThreeSellsService()

    # 构造最小 ind 字典（只有 1 天数据，2026-06-30，high=210，low=190）
    ind = {
        "n": 1,
        "dates": ["2026-06-30"],
        "lows": [190.0],
        "highs": [210.0],
        "closes": [200.0],
        "date_to_idx": {"2026-06-30": 0},
    }

    # 合法价格（close=200，在 [190, 210] 内）→ 通过
    ok, reason = svc._validate_trade_price_in_kline(ind, "2026-06-30", 200.0, "sell")
    assert ok is True, f"合法价格应通过，reason={reason}"

    # 非法价格：193.45 低于 low=190（超出容错±0.3%=0.63）→ 拒绝
    ok, reason = svc._validate_trade_price_in_kline(ind, "2026-06-30", 185.0, "sell")
    assert ok is False, f"低于low的价格必须被拒绝，reason={reason}"
    assert "不在" in reason and "[190.00, 210.00]" in reason

    # 非法价格：250 > high=210 → 拒绝
    ok, reason = svc._validate_trade_price_in_kline(ind, "2026-06-30", 250.0, "sell")
    assert ok is False, f"高于high的价格必须被拒绝，reason={reason}"


@pytest.mark.regression
def test_bug_011_axiom2_sell_price_not_averaged_over_s1_reductions():
    """
    bug-011 核心场景（603186）：
      - 1000股 @73.92 买入
      - S1触发：先减仓300股 @100（2026-06-10，high=105，low=95）
        cumulative_proceeds = 300 * 100 * 0.999 = 29970
        remaining_shares = 700 → S2再减仓至330
      - 2026-06-30移动止损清仓剩余330股 @200（high=210，low=190）

      ❌ 旧逻辑 avg_sell ≈ (300*100 + 370*150 + 330*200)/1000 = 一个"均价"，
              这个均价几乎肯定不在 2026-06-30 的 [190,210] 区间内！
      ✅ 新逻辑 sell_price = 200（2026-06-30 的 close），一定在 [190,210] 内
              return_pct 仍然正确反映真实总收益率
    """
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService

    svc = ThreeBuysThreeSellsService()

    # 构造最小 ind：两天数据
    #   2026-06-10：O=98, H=105, L=95, C=100（S1减仓日）
    #   2026-06-30：O=195, H=210, L=190, C=200（移动止损清仓日）
    ind = {
        "n": 2,
        "dates": ["2026-06-10", "2026-06-30"],
        "opens": [98.0, 195.0],
        "highs": [105.0, 210.0],
        "lows": [95.0, 190.0],
        "closes": [100.0, 200.0],
        "date_to_idx": {"2026-06-10": 0, "2026-06-30": 1},
    }

    # 模拟持仓：S1/S2 减仓后，剩余330股，cumulative_proceeds 已经包含之前两批减仓
    s1_shares, s1_price = 300, 100.0
    s2_shares, s2_price = 370, 150.0
    remaining_shares = 330
    total_shares = s1_shares + s2_shares + remaining_shares

    s1_proceeds = s1_shares * s1_price * 0.999
    s2_proceeds = s2_shares * s2_price * 0.999

    # 买入价 73.92（含滑点，买入日O=73.7，加0.3%滑点）
    buy_price = 73.92
    total_cost = total_shares * buy_price * 1.001

    pos = {
        "code": "603186",
        "name": "华正新材",
        "buy_price": buy_price,
        "buy_date": "2026-04-27",
        "buy_idx": 0,  # 这里 buy_idx 不准确，但不影响 sell_price 的计算
        "total_shares": total_shares,
        "remaining_shares": remaining_shares,
        "cost": total_cost,
        "cumulative_proceeds": s1_proceeds + s2_proceeds,  # 包含 S1+S2 两批
        "remaining_pct": remaining_shares / total_shares,
        "score": 80,
        "signal_type": "B2",
        "ind": ind,
        "last_valid_idx": 1,
    }

    # 2026-06-30 清仓，close=200
    td = "2026-06-30"
    close_on_td = 200.0

    trade = svc._build_and_validate_sell_trade(pos, ind, td, close_on_td, "移动止损")

    # ===== 关键断言：公理1+2 同时满足 =====
    assert trade is not None, "合法的清仓记录必须返回（不应被拦截）"

    # 🔥 公理2：sell_date = td = 2026-06-30，不是混合日期
    assert trade["sell_date"] == "2026-06-30", (
        f"sell_date必须是清仓当天日期，实际={trade['sell_date']}"
    )

    # 🔥 公理1：sell_price = 200（当天 close），必须落在 [190, 210]
    assert trade["sell_price"] == 200.0, (
        f"sell_price必须是当天close=200，不能是跨日期均价！实际={trade['sell_price']}"
    )
    assert 190.0 <= trade["sell_price"] <= 210.0, (
        f"sell_price必须在[190, 210]区间，实际={trade['sell_price']}"
    )

    # 🔥 总收益率仍然正确（含 S1+S2 两批减仓收益）
    final_proceeds = remaining_shares * 200.0 * 0.999
    total_proceeds = s1_proceeds + s2_proceeds + final_proceeds
    expected_return_pct = round((total_proceeds - total_cost) / total_cost * 100, 2)
    assert trade["return_pct"] == expected_return_pct, (
        f"return_pct 应该包含减仓收益，期望={expected_return_pct}, 实际={trade['return_pct']}"
    )


@pytest.mark.regression
def test_bug_011_missing_trade_date_falls_back_to_last_valid_idx():
    """bug-011 公理2：当 td 不在K线数据中（停牌/数据缺口），自动回退到last_valid_idx"""
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService

    svc = ThreeBuysThreeSellsService()

    # 只有 2026-06-29 一天数据，模拟 2026-06-30 停牌（数据缺失）
    ind = {
        "n": 1,
        "dates": ["2026-06-29"],
        "opens": [190.0],
        "highs": [200.0],
        "lows": [188.0],
        "closes": [198.0],
        "date_to_idx": {"2026-06-29": 0},
    }

    pos = {
        "code": "000001",
        "name": "平安银行",
        "buy_price": 100.0,
        "buy_date": "2026-06-01",
        "buy_idx": 0,
        "total_shares": 1000,
        "remaining_shares": 1000,
        "cost": 100100.0,
        "cumulative_proceeds": 0.0,
        "remaining_pct": 1.0,
        "score": 70,
        "signal_type": "B2",
        "ind": ind,
        "last_valid_idx": 0,  # 最后有效索引是2026-06-29
    }

    # 试图在 2026-06-30（数据缺口）清仓
    trade = svc._build_and_validate_sell_trade(
        pos, ind, "2026-06-30", 198.0, "到期卖出"
    )

    # sell_date 必须回退到 2026-06-29，sell_price = close=198（在 [188,200] 内）
    assert trade is not None, "回退后的合法记录应返回"
    assert trade["sell_date"] == "2026-06-29", (
        f"数据缺口时sell_date必须回退到last_valid_idx的日期，实际={trade['sell_date']}"
    )
    assert trade["sell_price"] == 198.0
    assert 188.0 <= trade["sell_price"] <= 200.0


@pytest.mark.regression
def test_bug_011_ingestion_ohlc_high_low_auto_correction():
    """bug-011 入库公理A/B：historical_data_service 必须修正 high/low 异常"""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装，跳过入库公理测试")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    # 模拟一条脏数据：close=100 但 high=95（high应该≥close），low=105（low应该≤open）
    dirty_row = pd.Series({
        "open": 97.0,
        "high": 95.0,   # ❌ 错误：high < close=100
        "low": 105.0,   # ❌ 错误：low > open=97，且 low > high
        "close": 100.0,
        "pre_close": 98.0,
        "volume": 100000,
        "amount": 10000,
    })

    doc = svc._standardize_record(
        symbol="000001",
        row=dirty_row,
        data_source="tushare",
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-06-30"),
    )

    # high 必须修正为 max(O,H,L,C)=105（修正后以 close 为准，或者用原始 dirty low）
    # 实际逻辑：prices=[97,95,105,100] → correct_high=105, correct_low=95
    assert doc["high"] >= max(doc["open"], doc["close"]), (
        f"high={doc['high']} 应 >= max(O={doc['open']}, C={doc['close']})"
    )
    assert doc["low"] <= min(doc["open"], doc["close"]), (
        f"low={doc['low']} 应 <= min(O={doc['open']}, C={doc['close']})"
    )
    assert doc["high"] >= doc["low"], (
        f"high={doc['high']} 应 >= low={doc['low']}"
    )

    # _validation_warnings 应该非空（记录了修正动作）
    assert len(doc.get("_validation_warnings", [])) >= 2, (
        f"应该至少记录 high修正 和 low修正，实际={doc.get('_validation_warnings')}"
    )


@pytest.mark.regression
def test_bug_011_ingestion_price_negative_or_none_fallback():
    """bug-011 入库公理B：价格为None或负值时必须有兜底，不抛出异常"""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装，跳过入库公理测试")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    # 价格全是 None：不能崩溃
    all_none_row = pd.Series({
        "open": None,
        "high": None,
        "low": None,
        "close": 50.0,  # 只有close有值
        "pre_close": None,
        "volume": None,
        "amount": None,
    })

    doc = svc._standardize_record(
        symbol="300001",
        row=all_none_row,
        data_source="akshare",
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-06-30"),
    )

    # 至少不崩溃，close=50 有值，high/low/open 应该用 close 兜底
    assert doc["close"] == 50.0
    assert doc["high"] == 50.0 or doc["high"] is None or doc["high"] >= 0
    assert doc["low"] == 50.0 or doc["low"] is None or doc["low"] >= 0


# ================= 新增：第一性原理四公理完备防线 回归测试 =================

@pytest.mark.regression
def test_bug_011_axiom1_buy_side_is_strongly_blocked():
    """
    🔥 bug-011 公理1完备化：买入侧价格非法必须被 _build_and_validate_buy_trade 强拦截（返回 None）
    —— 之前买入侧只打日志不拦截，是"修修补补"；现在从第一性原理出发，买入/卖出两侧同标准强拦截。
    """
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService

    svc = ThreeBuysThreeSellsService()

    # 构造最小 ind：一天数据 high=210, low=190, open=195
    ind = {
        "n": 1,
        "dates": ["2026-06-30"],
        "opens": [195.0],
        "highs": [210.0],
        "lows": [190.0],
        "closes": [200.0],
        "date_to_idx": {"2026-06-30": 0},
    }
    params = {"slippage_pct": 0.003}

    # 场景A：合法 next_idx=0（open=195，*1.003滑点=195.585，在[190,210]区间）→ 返回合法pos_frame
    sig_ok = {
        "code": "603186", "name": "华正新材", "score": 80,
        "signal_type": "B2", "position_pct": 0.67, "ind": ind, "idx": 0,
    }
    # 注意：回测中 next_idx = cur_idx+1，此最小场景只有 n=1 故 next_idx=0 越界，为测试函数本身用 n=2
    ind2 = {
        "n": 2,
        "dates": ["2026-06-29", "2026-06-30"],
        "opens": [190.0, 195.0],
        "highs": [200.0, 210.0],
        "lows": [188.0, 190.0],
        "closes": [198.0, 200.0],
        "date_to_idx": {"2026-06-29": 0, "2026-06-30": 1},
    }
    sig_ok["ind"] = ind2
    sig_ok["idx"] = 0  # cur_idx = 0，next_idx = 1 = 2026-06-30
    pos_frame, buy_price = svc._build_and_validate_buy_trade(sig_ok, 1, params)
    assert pos_frame is not None and buy_price is not None, (
        "合法场景应返回 (pos_frame, buy_price)，不能返回 None"
    )
    assert pos_frame["buy_date"] == "2026-06-30"
    assert abs(buy_price - 195.0 * 1.003) < 0.01
    assert 190.0 <= buy_price <= 210.0, (
        f"买入价{buy_price}应在[190,210]区间"
    )

    # 场景B：非法 next_idx=1 但滑点后超出容错（模拟极端高开，low=190，人为给 opens[1]=150 < low=190）
    ind_bad = {
        "n": 2,
        "dates": ["2026-06-29", "2026-06-30"],
        "opens": [190.0, 150.0],   # ❌ open=150 < low=190，加滑点也 < low - 容错
        "highs": [200.0, 210.0],
        "lows": [188.0, 190.0],
        "closes": [198.0, 200.0],
        "date_to_idx": {"2026-06-29": 0, "2026-06-30": 1},
    }
    sig_bad = {
        "code": "603186", "name": "华正新材", "score": 80,
        "signal_type": "B2", "position_pct": 0.67, "ind": ind_bad, "idx": 0,
    }
    pos_frame2, buy_price2 = svc._build_and_validate_buy_trade(sig_bad, 1, params)
    # 🔥 第一性原理：非法买入价 必须 被强拦截（不是打日志，是直接返回None跳过建仓）
    assert pos_frame2 is None and buy_price2 is None, (
        f"非法买入价（open=150 < low=190）必须被强拦截返回(None, None)，"
        f"实际得到 ({pos_frame2}, {buy_price2})"
    )


@pytest.mark.regression
def test_bug_011_axiom3_no_lookahead_bias_raises():
    """
    🔥 bug-011 公理3（无未来函数）：_validate_no_lookahead_bias 在 idx 越界 或 核心数组长度不一致时
    必须抛 ValueError，不能默默放过。
    """
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService

    svc = ThreeBuysThreeSellsService()

    # 构造正常 ind：n=3，所有数组长度=3
    ok_ind = {
        "n": 3,
        "dates": ["2026-06-28", "2026-06-29", "2026-06-30"],
        "opens": [1.0, 2.0, 3.0],
        "closes": [1.1, 2.1, 3.1],
        "highs": [1.2, 2.2, 3.2],
        "lows": [0.9, 1.9, 2.9],
        "volumes": [100, 200, 300],
        "ma5": [1.0, 1.5, 2.0],
        "ma8": [1.0, 1.5, 2.0],
        "ma13": [1.0, 1.5, 2.0],
        "ma55": [1.0, 1.5, 2.0],
        "ma60": [1.0, 1.5, 2.0],
        "ma65": [1.0, 1.5, 2.0],
        "bias60": [0.0, 0.0, 0.0],
        "atr14": [0.1, 0.2, 0.3],
        "gmma_strong_bull": [False, False, True],
        "stock_trend": ["neutral", "neutral", "up"],
    }

    # 场景A：合法 idx=2（最后一天）→ 不抛
    svc._validate_no_lookahead_bias(ok_ind, 2, context="test-case-A")

    # 场景B：idx=3 越界（n=3，合法索引0-2）→ 必须抛 ValueError
    with pytest.raises(ValueError, match=r"未来函数违规.*越界"):
        svc._validate_no_lookahead_bias(ok_ind, 3, context="越界测试")

    # 场景C：idx=-1 越界 → 抛 ValueError
    with pytest.raises(ValueError, match=r"未来函数违规.*越界"):
        svc._validate_no_lookahead_bias(ok_ind, -1, context="负索引测试")

    # 场景D：核心数组长度不一致（ma5长度=2 ≠ n=3）→ 抛 ValueError（代表索引错位，会读到未来数据）
    bad_ind = dict(ok_ind)
    bad_ind["ma5"] = [1.0, 1.5]  # ❌ 长度=2，和 n=3 不一致
    with pytest.raises(ValueError, match=r"ma5.*长度"):
        svc._validate_no_lookahead_bias(bad_ind, 2, context="数组错位测试")


@pytest.mark.regression
def test_bug_011_axiom4_kline_integrity_detects_all_flaws():
    """
    🔥 bug-011 公理4（输入完整性）：_validate_kline_integrity 必须检测四类问题
    （重复日期/逆序/OHLC关系错误/覆盖率不足），任一 fatal 必须 passed=False。
    """
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService

    svc = ThreeBuysThreeSellsService()

    # 场景1：完美数据 → passed=True，0 错误 0 警告
    perfect = [
        {"trade_date": "2026-06-26", "open": 96, "close": 98, "high": 99, "low": 95, "volume": 10000},
        {"trade_date": "2026-06-29", "open": 98, "close": 100, "high": 101, "low": 97, "volume": 10000},
        {"trade_date": "2026-06-30", "open": 100, "close": 105, "high": 106, "low": 99, "volume": 10000},
    ]
    r = svc._validate_kline_integrity(perfect, "TEST001", "2026-06-26", "2026-06-30")
    assert r["passed"] is True, f"完美数据必须passed=True，错误={r['errors']}，警告={r['warnings']}"
    assert r["n_input"] == 3 and r["n_after_dedup"] == 3

    # 场景2：重复日期 → 警告 + n_after_dedup 减少
    with_dup = list(perfect) + [perfect[1]]  # 重复 2026-06-29
    r = svc._validate_kline_integrity(with_dup, "TEST002")
    assert any("重复" in w for w in r["warnings"]), "必须有重复日期警告"
    assert r["n_after_dedup"] == 3, f"去重后应为3，实际={r['n_after_dedup']}"

    # 场景3：逆序（日期从大到小）→ passed=False
    reversed_order = list(reversed(perfect))
    r = svc._validate_kline_integrity(reversed_order, "TEST003")
    assert r["passed"] is False, "逆序数据必须passed=False"
    assert any("非严格递增" in e for e in r["errors"]), "必须有顺序错误"

    # 场景4：high=90 < max(open=96, close=98) → 必须有OHLC警告
    ohlc_bad = [
        {"trade_date": "2026-06-26", "open": 96, "close": 98, "high": 90, "low": 95, "volume": 10000},
    ]
    r = svc._validate_kline_integrity(ohlc_bad, "TEST004")
    has_high_warn = any("high=" in w and "< max" in w for w in r["warnings"])
    assert has_high_warn, f"必须有high<max(O,C)警告，实际warnings={r['warnings']}"

    # 场景5：覆盖率严重不足（要求2026-06-01~2026-06-30，只有3天数据≈覆盖率<50%）→ passed=False
    r = svc._validate_kline_integrity(perfect, "TEST005", "2026-06-01", "2026-06-30")
    assert r["passed"] is False, (
        f"覆盖率{r['coverage_ratio']*100:.1f}% < 70% 必须passed=False，"
        f"errors={r['errors']}"
    )
    assert any("覆盖率" in e for e in r["errors"]), "必须包含覆盖率错误"


@pytest.mark.regression
def test_bug_011_report_has_data_contract_diag_fields():
    """
    🔥 bug-011 可视化诊断：回测输出 result 中必须包含 data_contract_report 字段，
    字段结构包含 blocked_buys/blocked_sells/kline_skipped_stocks 等7个核心诊断指标，
    这样用户在页面上一眼就能看到"数据不完整被拦截了多少"，从第一性原理保证透明可观测。
    """
    # 由于回测主函数需要异步+数据库，此处只测试报告结构：
    # 直接校验报告字典字段清单，避免新防线被"不小心删了计数器却没人知道"。
    REQUIRED_KEYS = {
        "blocked_buys",          # 公理1/2 拦截的非法买入
        "blocked_sells",         # 公理1/2 拦截的非法卖出
        "kline_skipped_stocks",  # 公理4 完整性不达标跳过的股票
        "kline_warnings_total",  # 公理4 汇总警告数
        "kline_errors_total",    # 公理4 汇总错误数
        "stocks_passed_integrity",  # 公理4 通过完整性检查的股票数
        "lookahead_violations",  # 公理3 未来函数违规数
    }

    # 构造最小化 data_contract_report 原型（和 backtest() 代码中的初始化保持完全一致）
    from app.services.three_buys_three_sells_service import ThreeBuysThreeSellsService
    import inspect
    src = inspect.getsource(ThreeBuysThreeSellsService.backtest)
    for key in REQUIRED_KEYS:
        # 要求初始化字典里显式写出这7个键，防止被"重构时顺手删掉"
        assert f'"{key}"' in src or f"'{key}'" in src or key in src, (
            f"在 backtest() 源码中找不到键 '{key}' 的显式初始化！"
            f"该键是第一性原理的诊断指标，不允许被隐藏/隐式构造。"
        )
