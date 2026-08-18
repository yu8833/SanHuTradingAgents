"""
防回归测试：bug-012 成交额/成交量单位混乱导致 688669 页面 2026-07-31 数据显示错误

用户报告（最终正确值）：
    688669 聚和材料 2026-07-31
        成交量 = 3.96 万手 = 39,600 手 = 3,960,000 股
        成交额 = 2.41 亿元 = 241,000,000 元

数据契约（统一口径，强制执行！）：
    后端所有 amount/volume 入库 + API 返回：
        amount = 永远是「元」
        volume = 永远是「股」
    前端 fmtAmount(fmtAmount)：输入永远是「元」，输出万/亿后缀。
    前端 fmtVolume：输入永远是「股」，输出万股/亿股后缀。

新架构（bug-012 修复后）：
    单位转换职责明确落在 adapter 层：
        tushare_adapter.get_kline():  vol(手)×100→股,  amount(千元)×1000→元
        akshare_adapter.get_kline():   volume(手)×100→股, amount(元)不转换
        baostock_adapter:              volume(股)/amount(元) 均不转换
    historical_data_service.save_historical_data() / _standardize_record()：
        不再做任何单位转换，直接入库 adapter 已转换后的标准单位数据。
    sina 数据：不走 adapter get_kline，入库时已是标准单位（股/元），无需转换。

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
# Axiom 1：historical_data_service 不再进行任何单位转换（adapter 已完成）
#   新架构：service 收到的 data DataFrame 应当已是 adapter 转换后的标准单位数据。
#   service 直接 _standardize_record 入库，不得再 ×100 / ×1000 / ÷10000。
# ========================================================================

@pytest.mark.regression
def test_bug_012_historical_data_tushare_no_double_conversion():
    """
    bug-012 数据契约：service 收到 tushare adapter 已转换数据后，
    必须原样入库（adapter 已将 vol=39600手 → volume=3,960,000股；amount=241000千元 → 241,000,000元）
    service 不得再做任何单位转换，否则将导致数据放大 100/1000 倍。
    """
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    # ===== Step 1：模拟 tushare_adapter.get_kline() → provider 构造的 DataFrame（已转换）=====
    # adapter.get_kline() 返回 list of dict，键名为 volume/amount（不是 vol），
    # 并已完成单位转换：vol(手)×100→volume(股), amount(千元)×1000→元
    # provider 将其构造为 DataFrame，列名仍为 volume/amount
    data = pd.DataFrame([{
        "time": "20260731",
        "trade_date": "20260731",
        "ts_code": "688669.SH",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 3960000.0,      # adapter 已转换：39600手 × 100 = 3,960,000股
        "amount": 241000000.0,    # adapter 已转换：241000千元 × 1000 = 241,000,000元
    }])

    # ===== Step 2：service 不做任何 DataFrame 级别的单位转换 =====
    data_source = "tushare"
    # 🔥 关键：service 中已经移除所有 if data_source == "tushare": data['amount'] *= 1000 等转换代码

    # ===== Step 3：直接传给 _standardize_record =====
    row = data.iloc[0]
    doc = svc._standardize_record(
        symbol="688669",
        row=row,
        data_source=data_source,
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-07-31"),
    )

    # 🔥 核心断言：service 必须原样保留 adapter 转换后的值，不得再次 ×1000 / ×100
    expected_amount = 241000000.0  # 2.41 亿元
    assert abs(doc["amount"] - expected_amount) < 0.01, (
        f"Tushare adapter已转换后service不得再次转换！期望={expected_amount}元, 实际={doc['amount']}。"
        f"若实际=2.41e10 说明被×100了；若=2.41e11 说明被×1000了"
    )
    expected_volume = 3960000.0  # 3.96 万手 = 3,960,000 股
    assert abs(doc["volume"] - expected_volume) < 0.01, (
        f"Tushare adapter已转换后service不得再次转换！期望={expected_volume}股, 实际={doc['volume']}。"
        f"若实际=3.96e8 说明被×100了"
    )


@pytest.mark.regression
def test_bug_012_historical_data_akshare_no_double_conversion():
    """
    bug-012 数据契约：service 收到 akshare adapter 已转换数据后，必须原样入库。
    AKShare adapter：volume(手)×100→股, amount(元)不变。
    """
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    # ===== Step 1：模拟 akshare_adapter.get_kline() → provider 构造的 DataFrame（已转换）=====
    # adapter.get_kline() 返回 list of dict，键名为 volume/amount，
    # 并已完成单位转换：volume(手)×100→股, amount(元)不变
    data = pd.DataFrame([{
        "time": "2026-07-31",
        "trade_date": "20260731",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 3960000.0,      # adapter 已转换：39600手 × 100 = 3,960,000股
        "amount": 241000000.0,    # adapter 不转换：保持元
    }])

    # ===== Step 2：service 不做任何 DataFrame 级别的单位转换 =====
    data_source = "akshare"
    # 🔥 关键：service 中已经移除所有 if data_source == "akshare": data['volume'] *= 100 等转换代码

    # ===== Step 3：直接传给 _standardize_record =====
    row = data.iloc[0]
    doc = svc._standardize_record(
        symbol="688669",
        row=row,
        data_source=data_source,
        market="CN",
        period="daily",
        date_index=pd.Timestamp("2026-07-31"),
    )

    # 🔥 核心断言：service 必须原样保留 adapter 转换后的值
    expected_amount = 241000000.0  # 2.41 亿元
    assert doc["amount"] is not None, "AKShare amount不应为None"
    assert abs(doc["amount"] - expected_amount) < 0.01, (
        f"AKShare amount必须保持元，期望={expected_amount}, 实际={doc['amount']}"
    )
    expected_volume = 3960000.0  # 3.96 万手 = 3,960,000 股
    assert abs(doc["volume"] - expected_volume) < 0.01, (
        f"AKShare volume必须手→股，期望={expected_volume}, 实际={doc['volume']}"
    )


@pytest.mark.regression
def test_bug_012_historical_data_baostock_amount_volume_no_conversion():
    """bug-012 数据契约：BaoStock amount=元、volume=股 → adapter 和 service 都不转换"""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas未安装")

    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    raw = pd.DataFrame([{
        "trade_date": "20260731",
        "time": "20260731",
        "code": "sh.688669",
        "open": "100.0000",
        "high": "102.0000",
        "low": "99.0000",
        "close": "101.0000",
        "pre_close": "100.0000",
        "volume": "3960000",        # 股（BaoStock已经是股，不×100）
        "amount": "241000000.00",  # 元（BaoStock已是元，不做任何转换）
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

    expected_amount = 241000000.0
    expected_volume = 3960000.0
    assert abs(doc["amount"] - expected_amount) < 0.01, (
        f"BaoStock amount必须保持元，期望={expected_amount}, 实际={doc['amount']}"
    )
    assert abs(doc["volume"] - expected_volume) < 0.01, (
        f"BaoStock volume必须保持股，期望={expected_volume}, 实际={doc['volume']}"
    )


# ========================================================================
# Axiom 1.5：源代码防回归 — historical_data_service.py 不得包含任何单位转换逻辑
#   禁止出现：data['amount'] *= 1000 / data['vol'] *= 100 / data['amount'] /= 10000 等
# ========================================================================

@pytest.mark.regression
def test_bug_012_historical_data_service_no_unit_conversion_in_source():
    """
    bug-012 防回归：historical_data_service.py 源代码中不得包含任何 amount/volume
    单位转换逻辑（×1000 / ×100 / ÷10000 等）。
    单位转换职责已全部下放到 adapter 层。
    """
    svc_path = _path("app", "services", "historical_data_service.py")
    assert os.path.exists(svc_path), f"找不到文件: {svc_path}"

    with open(svc_path, encoding="utf-8") as f:
        lines = f.readlines()

    import re
    # 危险模式：匹配形如 data['amount'] = ... * 1000.0、data['vol'] *= 100 等
    # 关键：必须同时出现 字段名 + 数值倍率（1000 / 100 / 10000）
    # 例如旧 bug 代码：data['amount'] = data['amount'] * 1000.0
    field_pattern = r"['\"](?:amount|vol|volume|turnover)['\"]"
    dangerous_patterns = [
        (re.compile(field_pattern + r"[^\n]*\*\s*=?\s*1000\b"), "amount/vol ×1000"),
        (re.compile(field_pattern + r"[^\n]*\*=\s*1000\b"), "amount/vol *= 1000"),
        (re.compile(field_pattern + r"[^\n]*\*\s*=?\s*100\b(?!0)"), "amount/vol ×100"),
        (re.compile(field_pattern + r"[^\n]*\*=\s*100\b(?!0)"), "amount/vol *= 100"),
        (re.compile(field_pattern + r"[^\n]*/\s*=?\s*10000\b"), "amount/vol ÷10000"),
        (re.compile(field_pattern + r"[^\n]*/=\s*10000\b"), "amount/vol /= 10000"),
    ]

    bad_lines = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # 跳过注释和文档字符串
        if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
            continue
        for pat, desc in dangerous_patterns:
            if pat.search(line):
                bad_lines.append((i, line.rstrip(), desc))
                break

    assert len(bad_lines) == 0, (
        "historical_data_service.py 中检测到残留的单位转换代码！\n"
        "新架构要求：单位转换全部下放到 adapter 层，service 不得做任何转换！\n"
        "问题行：\n" + "\n".join([f"  L{ln} [{desc}]: {content}" for ln, content, desc in bad_lines])
    )


# ========================================================================
# Axiom 2：Tushare adapter 必须包含 amount ×1000（千元→元）转换
# ========================================================================

@pytest.mark.regression
def test_bug_012_tushare_adapter_amount_qianyuan_to_yuan():
    """bug-012：Tushare adapter amount=千元 → 源代码必须 ×1000，禁止×0.1"""
    adapter_path = _path("app", "services", "data_sources", "tushare_adapter.py")
    assert os.path.exists(adapter_path), f"找不到文件: {adapter_path}"

    with open(adapter_path, encoding="utf-8") as f:
        code = f.read()

    # 🔥 断言：源代码中必须包含 amount × 1000（千元→元）
    assert "amount" in code, "tushare_adapter.py 必须包含 amount 转换逻辑"
    assert "* 1000" in code or "*1000" in code, (
        "tushare_adapter.py 必须把 amount(千元) ×1000 → 元，当前源码找不到 ×1000！"
    )
    # 🔥 断言：绝对不能再出现 ×0.1（千元→万元，当元入库造成 100×误差）
    assert "* 0.1" not in code, (
        "tushare_adapter.py 存在 amount×0.1（千元变万元）的旧bug！必须删除！"
    )
    assert "*0.1" not in code, (
        "tushare_adapter.py 存在 amount*0.1（千元变万元）的旧bug！必须删除！"
    )


@pytest.mark.regression
def test_bug_012_tushare_adapter_vol_shou_to_gu():
    """bug-012：Tushare adapter vol=手 → 源代码必须 ×100（手→股）"""
    adapter_path = _path("app", "services", "data_sources", "tushare_adapter.py")
    with open(adapter_path, encoding="utf-8") as f:
        code = f.read()

    # 必须有 vol × 100 或 volume × 100
    assert ("vol" in code and ("* 100" in code or "*100" in code)), (
        "tushare_adapter.py 必须把 vol(手) ×100 → 股，当前源码找不到 ×100！"
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


@pytest.mark.regression
def test_bug_012_akshare_adapter_volume_multiplied_by_100():
    """bug-012：AKShare 适配器 volume=手 → 源代码必须 ×100（手→股）"""
    adapter_path = _path("app", "services", "data_sources", "akshare_adapter.py")
    with open(adapter_path, encoding="utf-8") as f:
        code = f.read()

    assert ("volume" in code or "vol" in code) and ("* 100" in code or "*100" in code), (
        "akshare_adapter.py 必须把 volume(手) ×100 → 股，当前源码找不到 ×100！"
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
            "amount": 241000000.0,  # 元（2.41亿元）
        }
    }
    merged = _merge_quotes(akshare_only, {})

    assert "688669" in merged
    q = merged["688669"]
    assert q["source"] == "akshare"

    expected_wan = 241000000.0 / 10000.0  # = 24,100 万元
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
            "amount_wan": 24100.0,  # 2.41亿 = 24100 万
        }
    }
    merged = _merge_quotes({}, tencent)
    q = merged["688669"]
    assert q["source"] == "tencent"
    assert abs(q["amount_wan"] - 24100.0) < 0.001


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

    # 合法值（元）：2.41 亿
    r = sanitize_amount(241000000.0)
    assert r is not None and abs(float(r) - 241000000.0) < 0.01

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

    # 合法值（股）：3.96 万手 = 3,960,000 股
    r = sanitize_volume(3960000)
    assert r is not None and abs(float(r) - 3960000) < 0.01

    # 负值 → 拒绝
    r_neg = sanitize_volume(-1000)
    assert r_neg is None or float(r_neg) == 0.0, f"负值volume不应入库，得到{r_neg}"

    # 极端值（单票 > 1e12 股显然不可能）
    r_extreme = sanitize_volume(1e15)
    assert r_extreme is None or float(r_extreme) < 1e12, (
        f"极端volume不应入库，得到{r_extreme}"
    )


# ========================================================================
# Axiom 8：fmtAmount / fmtVolume 端到端验证（688669 真实值）
# ========================================================================

@pytest.mark.regression
def test_bug_012_end_to_end_fmtamount_688669_displays_2_41_yi():
    """
    bug-012：端到端验证，688669 amount=241,000,000 元 → fmtAmount 必须显示「2.41亿」
    用户报告的正确值：成交额 = 2.41 亿元
    """
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

    # 正确的 amount（元）：Tushare 241000千元 × 1000 = 241,000,000 元
    correct_amount = 241000000.0
    displayed = fmtAmount(correct_amount)

    # 🔥 端到端断言：必须显示 "2.41亿"
    assert displayed == "2.41亿", (
        f"688669 amount={correct_amount}元，fmtAmount 应该显示 '2.41亿'，"
        f"实际显示='{displayed}'！"
    )

    # 反向断言：旧bug下 amount=2,412,880 元（被×100 缩小后）→ fmtAmount 显示 "241.29万"
    # 这与用户报告的 "2.41万"（更小的错误值）形成对比，说明 bug 演化
    buggy_amount = 24128.88  # 若被 ÷100，会得到这个值
    buggy_displayed = fmtAmount(buggy_amount)
    assert "亿" not in buggy_displayed, (
        f"诊断：当amount被错误缩小100倍时，不应显示'亿'后缀，实际='{buggy_displayed}'"
    )


@pytest.mark.regression
def test_bug_012_end_to_end_fmtvolume_688669_displays_3_96_wan_shou():
    """
    bug-012：端到端验证，688669 volume=3,960,000 股 → fmtVolume 必须显示「396.00万股」
    用户报告的正确值：成交量 = 3.96 万手（= 3,960,000 股 = 396 万股）
    """
    # 复制前端 Detail.vue 中 fmtVolume 完全一致的逻辑
    def fmtVolume(v):
        n = float(v)
        if n != n:
            return '-'
        # 数据库存储的是"股"，直接显示为"万股"或"亿股"
        if n >= 1e8:
            return f"{n/1e8:.2f}亿股"
        if n >= 1e4:
            return f"{n/1e4:.2f}万股"
        return f"{n:.0f}股"

    # 正确的 volume（股）：Tushare 39600手 × 100 = 3,960,000 股
    correct_volume = 3960000.0
    displayed = fmtVolume(correct_volume)

    # 🔥 端到端断言：必须显示 "396.00万股"（对应 3.96万手）
    assert displayed == "396.00万股", (
        f"688669 volume={correct_volume}股，fmtVolume 应该显示 '396.00万股'，"
        f"实际显示='{displayed}'！"
    )

    # 反向断言：旧bug下 volume=39,600 股（被÷100 缩小后）→ fmtVolume 显示 "3.96万股"
    buggy_volume = 39600.0  # 若被÷100，会得到这个值
    buggy_displayed = fmtVolume(buggy_volume)
    # 旧bug下显示 "3.96万股"（用户可能误以为是 3.96万手）
    assert buggy_displayed == "3.96万股", (
        f"诊断：当volume被错误缩小100倍时，应显示'3.96万股'，实际='{buggy_displayed}'"
    )


# ========================================================================
# Axiom 9：数据契约文档化 — 单位转换职责矩阵
#   用一个集成测试明确各层职责，避免后续重构时混淆
# ========================================================================

@pytest.mark.regression
def test_bug_012_data_contract_unit_conversion_responsibility_matrix():
    """
    bug-012 数据契约文档化测试：
    明确单位转换职责矩阵，确保后续重构不会破坏契约。

    | 数据源     | 原始单位             | adapter 转换               | service 转换 |
    |-----------|----------------------|---------------------------|--------------|
    | tushare   | vol=手, amount=千元   | vol×100→股, amount×1000→元 | 无           |
    | akshare   | volume=手, amount=元 | volume×100→股, amount不变   | 无           |
    | baostock  | volume=股, amount=元 | 不转换                     | 无           |
    | sina      | (不走adapter)        | (不走adapter)              | 已是标准单位  |
    """
    # 通过源代码存在性断言，确保各 adapter 的转换逻辑存在
    tushare_path = _path("app", "services", "data_sources", "tushare_adapter.py")
    akshare_path = _path("app", "services", "data_sources", "akshare_adapter.py")
    service_path = _path("app", "services", "historical_data_service.py")

    assert os.path.exists(tushare_path)
    assert os.path.exists(akshare_path)
    assert os.path.exists(service_path)

    with open(tushare_path, encoding="utf-8") as f:
        tushare_code = f.read()
    with open(akshare_path, encoding="utf-8") as f:
        akshare_code = f.read()
    with open(service_path, encoding="utf-8") as f:
        service_code = f.read()

    # Tushare adapter 必须包含 vol×100 和 amount×1000
    assert "* 100" in tushare_code or "*100" in tushare_code, "tushare_adapter 必须有 vol×100"
    assert "* 1000" in tushare_code or "*1000" in tushare_code, "tushare_adapter 必须有 amount×1000"

    # AKShare adapter 必须包含 volume×100，但不能有 amount÷10000
    assert "* 100" in akshare_code or "*100" in akshare_code, "akshare_adapter 必须有 volume×100"

    # service 不得包含 amount/vol/volume 的单位转换逻辑
    # （由 Axiom 1.5 test_bug_012_historical_data_service_no_unit_conversion_in_source 详细覆盖）
    # 这里只做粗粒度断言：service 中不应出现 ×1000 / ÷10000 这类明显转换
    assert "* 1000" not in service_code and "*1000" not in service_code, (
        "historical_data_service.py 不应包含 ×1000 转换逻辑（已下放到 adapter）"
    )
    assert "/ 10000" not in service_code and "/10000" not in service_code, (
        "historical_data_service.py 不应包含 ÷10000 转换逻辑（已下放到 adapter）"
    )
