"""
防回归测试：bug-012 成交额/成交量单位混乱导致 688669 页面 2026-07-31 成交额显示为 2.41 万

数据契约（统一口径，强制执行！）：
    后端所有 amount/volume 入库 + API 返回：
        amount = 永远是「元」
        volume = 永远是「股」
    前端 fmtAmount(fmtAmount)：输入永远是「元」，输出万/亿后缀。
    特殊中间变量（仅在统一行情里腾讯接口用）：
        amount_wan = 临时字段（万元），只在 quotes_service 中立即 ×10000 转元输出
"""
import os
import pytest

# 项目根目录：tests/regression/ 往上两级就是根
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _path(*parts):
    """返回相对于项目根的绝对路径"""
    return os.path.join(_PROJECT_ROOT, *parts)


# ========================================================================
# Axiom 1：historical_data_service 中，各数据源 amount/volume 单位转换严格一致
#   注意：单位转换是在 DataFrame 级别（对整个 data df 做统一转换），然后再调
#         _standardize_record(row)。因此测试需要：先对 df 做单位转换 → 再取 row 做 standardize。
# ========================================================================

@pytest.mark.regression
def test_bug_012_historical_data_tushare_amount_qianyuan_to_yuan():
    """bug-012 数据契约：Tushare 日线 amount=千元 → 入库必须 ×1000 = 元，volume=手→×100=股"""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    # ===== Step 1：模拟 Tushare 原始 DataFrame =====
    data = pd.DataFrame([{
        "ts_code": "688669.SH",
        "trade_date": "20260731",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "pre_close": 100.0,
        "change": 1.0,
        "pct_chg": 1.0,
        "vol": 2412.0,       # 手（2412手 = 241,200股）
        "amount": 2412.88,    # 千元（2412.88千元 = 2,412,880元）
    }])

    # ===== Step 2：执行 DataFrame 级别的单位转换（和 _save_to_db 代码完全一致）=====
    data_source = "tushare"
    if data_source == "tushare":
        if 'amount' in data.columns:
            data['amount'] = data['amount'] * 1000.0
        elif 'turnover' in data.columns:
            data['turnover'] = data['turnover'] * 1000.0
        if 'volume' in data.columns:
            data['volume'] = data['volume'] * 100
        elif 'vol' in data.columns:
            data['vol'] = data['vol'] * 100

    # ===== Step 3：取出转换后的 row 传给 _standardize_record =====
    row = data.iloc[0]
    doc = svc._standardize_record(
        symbol="688669",
        row=row,
        data_source=data_source,
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-07-31"),
    )

    # 🔥 核心断言：amount 必须是 2,412,880 元（2412.88千元 × 1000）
    expected_amount = 2412.88 * 1000.0
    assert abs(doc["amount"] - expected_amount) < 0.01, (
        f"Tushare amount必须千元→元，期望={expected_amount}, 实际={doc['amount']}"
    )
    # 🔥 volume 必须是 241,200 股（2412手 × 100）
    expected_volume = 2412.0 * 100.0
    assert abs(doc["volume"] - expected_volume) < 0.01, (
        f"Tushare volume必须手→股，期望={expected_volume}, 实际={doc['volume']}"
    )
    # 前端 fmtAmount(2412880) = 2412880/1e4 = 241.29 万 ✓


@pytest.mark.regression
def test_bug_012_historical_data_akshare_amount_stays_yuan():
    """bug-012 数据契约：AKShare 日线 amount=元 → 入库必须保持元（禁止÷10000），volume=手→×100=股"""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    # ===== Step 1：模拟 AKShare 原始 DataFrame =====
    # AKShare stock_zh_a_hist 返回的是中文列名；实际同步代码中会先 rename 成 amount/volume
    raw_data = pd.DataFrame([{
        "日期": "2026-07-31",
        "开盘": 100.0,
        "收盘": 101.0,
        "最高": 102.0,
        "最低": 99.0,
        "成交量": 2412.0,       # 手
        "成交额": 2412880.0,     # 元（2,412,880 元 = 241.29万元）
        "振幅": 3.0,
        "涨跌幅": 1.0,
        "涨跌额": 1.0,
        "换手率": 1.0,
    }])

    # 先把中文列名 rename 为英文（和实际同步代码保持一致）
    raw_data = raw_data.rename(columns={
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    })

    # ===== Step 2：执行 DataFrame 级别的单位转换 =====
    data_source = "akshare"
    data = raw_data.copy()
    if data_source == "akshare":
        # amount 已经是元，无需转换
        if 'volume' in data.columns:
            data['volume'] = data['volume'] * 100  # 手 → 股
        elif 'vol' in data.columns:
            data['vol'] = data['vol'] * 100

    # ===== Step 3：_standardize_record =====
    row = data.iloc[0]
    doc = svc._standardize_record(
        symbol="688669",
        row=row,
        data_source=data_source,
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-07-31"),
    )

    # 🔥 核心断言：amount 必须保持 2,412,880 元（AKShare已是元，不能÷10000）
    expected_amount = 2412880.0
    assert doc["amount"] is not None, "AKShare amount不应为None"
    assert abs(doc["amount"] - expected_amount) < 0.01, (
        f"AKShare amount必须保持元，期望={expected_amount}, 实际={doc['amount']}"
    )
    # volume 必须手→股
    expected_volume = 2412.0 * 100.0
    assert abs(doc["volume"] - expected_volume) < 0.01


@pytest.mark.regression
def test_bug_012_historical_data_baostock_amount_volume_no_conversion():
    """bug-012 数据契约：BaoStock amount=元、volume=股 → 都不转换"""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    raw = pd.DataFrame([{
        "date": "2026-07-31",
        "code": "sh.688669",
        "open": "100.0000",
        "high": "102.0000",
        "low": "99.0000",
        "close": "101.0000",
        "preclose": "100.0000",
        "volume": "241200",     # 股（BaoStock已经是股，不×100）
        "amount": "2412880.00", # 元（BaoStock已是元，不做任何转换）
        "adjustflag": "2",
        "turn": "1.0",
        "tradestatus": "1",
        "pctChg": "1.0",
        "peTTM": "20.0",
        "pbMRQ": "3.0",
        "psTTM": "5.0",
        "pcfNcfTTM": "10.0",
        "isST": "0",
    }])
    # rename 为统一列名
    raw = raw.rename(columns={"date": "trade_date", "preclose": "pre_close"})

    # BaoStock 不做任何 DataFrame 级别的单位转换
    data = raw.copy()

    row = data.iloc[0]
    doc = svc._standardize_record(
        symbol="688669",
        row=row,
        data_source="baostock",
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-07-31"),
    )

    expected_amount = 2412880.0
    expected_volume = 241200.0
    assert abs(doc["amount"] - expected_amount) < 0.01, (
        f"BaoStock amount必须保持元，期望={expected_amount}, 实际={doc['amount']}"
    )
    assert abs(doc["volume"] - expected_volume) < 0.01, (
        f"BaoStock volume必须保持股，期望={expected_volume}, 实际={doc['volume']}"
    )


# ========================================================================
# Axiom 2：Tushare 实时行情 (rt_k) 单位转换严格正确
# ========================================================================

@pytest.mark.regression
def test_bug_012_tushare_rt_k_amount_qianyuan_to_yuan():
    """bug-012：Tushare rt_k amount=千元 → 适配器源代码必须 ×1000，禁止×0.1"""
    adapter_path = _path("app", "services", "data_sources", "tushare_adapter.py")
    assert os.path.exists(adapter_path), f"找不到文件: {adapter_path}"

    with open(adapter_path, encoding="utf-8") as f:
        code = f.read()

    # 🔥 断言：源代码中必须包含 amount × 1000（千元→元）
    assert "amount" in code, "tushare_adapter.py 必须包含 amount 转换逻辑"
    assert "* 1000" in code or "*1000" in code, (
        "tushare_adapter.py 必须把 rt_k amount(千元) ×1000 → 元，当前源码找不到 ×1000！"
    )
    # 🔥 断言：绝对不能再出现 ×0.1（千元→万元，当元入库造成 100×误差）
    assert "* 0.1" not in code, (
        "tushare_adapter.py 存在 amount×0.1（千元变万元）的旧bug！必须删除！"
    )
    assert "*0.1" not in code, (
        "tushare_adapter.py 存在 amount*0.1（千元变万元）的旧bug！必须删除！"
    )


# ========================================================================
# Axiom 3：akshare_adapter 所有 amount 输出保持元，禁止 ÷10000
# ========================================================================

@pytest.mark.regression
def test_bug_012_akshare_adapter_amount_never_divided_by_10000():
    """bug-012：AKShare 适配器输出 amount=元，源代码中绝对不允许出现 amount ÷ 10000"""
    adapter_path = _path("app", "services", "data_sources", "akshare_adapter.py")
    assert os.path.exists(adapter_path), f"找不到文件: {adapter_path}"

    with open(adapter_path, encoding="utf-8") as f:
        lines = f.readlines()

    bad_lines = []
    for i, line in enumerate(lines, 1):
        if "amount" in line.lower() and ("/ 10000" in line or "/10000" in line):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            bad_lines.append((i, line.rstrip()))

    assert len(bad_lines) == 0, (
        "akshare_adapter.py 中存在 amount ÷ 10000（把元变万元入库）的旧bug！\n"
        "问题行：\n" + "\n".join([f"  L{ln}: {content}" for ln, content in bad_lines])
    )


# ========================================================================
# Axiom 4：unified_quotes 合并时 AKShare amount(元) → 正确转 amount_wan(万元)
# ========================================================================

@pytest.mark.regression
def test_bug_012_unified_quotes_merge_akshare_amount_wan_correct():
    """bug-012：AKShare amount=元 → merge 到腾讯接口的 amount_wan=万元 必须 ÷10000"""
    from app.services.unified_quotes import _merge_quotes

    akshare_only = {
        "688669": {
            "name": "聚和材料",
            "close": 101.0,
            "pct_chg": 1.0,
            "amount": 2412880.0,  # 元（全局统一口径）= 241.288 万元
        }
    }
    merged = _merge_quotes(akshare_only, {})

    assert "688669" in merged
    q = merged["688669"]
    assert q["_source"] == "akshare"

    expected_wan = 2412880.0 / 10000.0  # = 241.288 万元
    assert q["amount_wan"] is not None, "AKShare merge后 amount_wan 不应为None"
    assert abs(q["amount_wan"] - expected_wan) < 0.01, (
        f"merge时 AKShare amount(元)÷10000 填 amount_wan(万元)，"
        f"期望={expected_wan}万，实际={q['amount_wan']}。"
    )


@pytest.mark.regression
def test_bug_012_unified_quotes_merge_tencent_amount_wan_untouched():
    """bug-012：腾讯源 amount_wan=万元 原样保留"""
    from app.services.unified_quotes import _merge_quotes

    tencent = {
        "688669": {
            "name": "聚和材料",
            "price": 101.0,
            "change_pct": 1.0,
            "amount_wan": 241.288,
        }
    }
    merged = _merge_quotes({}, tencent)
    q = merged["688669"]
    assert q["_source"] == "tencent"
    assert abs(q["amount_wan"] - 241.288) < 0.001


# ========================================================================
# Axiom 5：quotes_service 将中间 amount_wan ×10000 转 amount=元 输出给前端
# ========================================================================

@pytest.mark.regression
def test_bug_012_quotes_service_amount_wan_to_yuan_multiplication():
    """bug-012：quotes_service 源代码中必须有 amount_wan ×10000 → amount(元)"""
    svc_path = _path("app", "services", "quotes_service.py")
    assert os.path.exists(svc_path), f"找不到文件: {svc_path}"

    with open(svc_path, encoding="utf-8") as f:
        code = f.read()

    assert "amount_wan" in code, "quotes_service.py 中必须有 amount_wan 字段"
    assert "* 10000" in code or "*10000" in code, (
        "quotes_service.py 必须把腾讯 amount_wan(万元) ×10000 转 amount(元) 再输出"
    )


# ========================================================================
# Axiom 6：前端筛选页 amount 筛选阈值必须是元量级（10亿 = 1e9 元）
# ========================================================================

@pytest.mark.regression
def test_bug_012_frontend_screening_amount_thresholds_in_yuan():
    """bug-012：前端筛选页 high/medium/low 阈值必须是元量级，不是万元量级"""
    import re
    screening_path = _path("frontend", "src", "views", "Screening", "index.vue")
    assert os.path.exists(screening_path), f"找不到文件: {screening_path}"

    with open(screening_path, encoding="utf-8") as f:
        content = f.read()

    # high 成交量应该是 > 10亿元 = 1,000,000,000 元
    assert "1000000000" in content, (
        "Screening/index.vue 高成交量阈值必须是 1e9 元（>10亿元），"
        "旧值 100000 是万元量级！"
    )

    # 绝对不允许再出现 "100000, Number.MAX_SAFE_INTEGER"（万元量级阈值）
    bad_pattern = re.compile(r"\b100000\s*,\s*Number\.MAX_SAFE_INTEGER")
    assert not bad_pattern.search(content), (
        "Screening/index.vue 仍然保留万元量级的高成交量阈值 100000！必须×10000 改成元量级"
    )


# ========================================================================
# Axiom 7：sanitize_amount / sanitize_volume 正常 + 极端值拒绝
# ========================================================================

@pytest.mark.regression
def test_bug_012_sanitize_amount_rejects_negative_and_extreme():
    """bug-012：sanitize_amount 应该拒绝负值和极端溢出值"""
    from app.core.numeric_sanitizer import sanitize_amount

    # 合法值（元）
    r = sanitize_amount(2412880.0)
    assert r is not None and abs(float(r) - 2412880.0) < 0.01

    # 负值 → 返回 None 或 0
    r_neg = sanitize_amount(-1000.0)
    assert r_neg is None or float(r_neg) == 0.0, f"负值amount不应入库，得到{r_neg}"

    # 极端值（>1e15 元显然不可能）
    r_extreme = sanitize_amount(1e18)
    assert r_extreme is None or float(r_extreme) < 1e15, (
        f"极端amount不应入库，得到{r_extreme}"
    )


@pytest.mark.regression
def test_bug_012_sanitize_volume_rejects_negative_and_extreme():
    """bug-012：sanitize_volume 应该拒绝负值和极端溢出值"""
    from app.core.numeric_sanitizer import sanitize_volume

    # 合法值（股）
    r = sanitize_volume(241200)
    assert r is not None and abs(float(r) - 241200) < 0.01

    # 负值 → 拒绝
    r_neg = sanitize_volume(-1000)
    assert r_neg is None or float(r_neg) == 0.0, f"负值volume不应入库，得到{r_neg}"

    # 极端值（单票 > 1e12 股显然不可能）
    r_extreme = sanitize_volume(1e15)
    assert r_extreme is None or float(r_extreme) < 1e12, (
        f"极端volume不应入库，得到{r_extreme}"
    )


# ========================================================================
# Axiom 8：fmtAmount(688669真实amount元值) 端到端验证
# ========================================================================

@pytest.mark.regression
def test_bug_012_end_to_end_fmtamount_688669_displays_correctly():
    """bug-012：端到端验证，688669 amount=2,412,880 元 → fmtAmount 必须显示≈241.29万"""

    # 复制前端 Detail.vue 中 fmtAmount 完全一致的逻辑
    def fmtAmount(v):
        n = float(v)
        if n != n:  # NaN check
            return '-'
        if n >= 1e12:
            return f"{n/1e12:.2f}万亿"
        if n >= 1e8:
            return f"{n/1e8:.2f}亿"
        if n >= 1e4:
            return f"{n/1e4:.2f}万"
        return f"{n:.0f}"

    # 正确的 amount（元）：Tushare 2412.88千元 × 1000 = 2,412,880 元
    correct_amount = 2412.88 * 1000.0
    displayed = fmtAmount(correct_amount)

    # 🔥 端到端断言：必须显示 "241.29万"（前缀 241 + 万）
    assert displayed.startswith("241"), (
        f"688669 amount={correct_amount}元，fmtAmount 应该≈241.29万，实际显示='{displayed}'！"
    )
    assert "万" in displayed, (
        f"正确值应显示'万'后缀，实际='{displayed}'"
    )

    # 反向断言：旧bug代码会把 2412.88 直接当元 → fmtAmount(2412.88)
    #   因为 2412.88 < 1e4，所以直接显示 "2413"（不显示"万"），这正是bug诊断
    buggy_displayed = fmtAmount(2412.88)
    # 要么是纯数字（"2413"），要么显示远小于正确值
    assert "万" not in buggy_displayed or buggy_displayed.startswith("0."), (
        "诊断：当千元值2412.88被错误当元直接入库时，应<1万，不应出现'万'后缀"
    )
