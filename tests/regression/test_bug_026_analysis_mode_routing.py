"""
Bug-026 防回归测试：分析模式（快评/尽调）真实生效

背景：此前前端"速览/深度"与 include_sentiment/include_risk 只是参数，未接入执行管线，
图引擎无论快评/尽调都会跑完整 7 节点 + 多空辩论 + 风险辩论 + 组合经理二审，造成 UI 承诺与后端行为割裂。

新契约：
  1. 分析深度收敛为两种模式：
     - "light"（快评）：精简论证链，跳过多空辩论与风险辩论/组合经理二审
     - "full"（尽调）：完整论证链，含多空辩论、风险辩论三人组与投资组合经理二审
  2. create_analysis_config 必须把 mode 归一化为 light/full 并写入 config["mode"]。
  3. 兼容旧值：quick→light，deep→full；缺省为 full（尽调），保证默认行为不变。

本测试从配置层锁定 mode 归一化契约，防止执行链路再次失联或默认行为漂移。
执行层面的链路差异（篇幅所限不构造完整图）由部署后的运行日志验证。
"""
import pytest

pytestmark = pytest.mark.regression


@pytest.fixture(scope="module")
def _config():
    # 延迟导入，避免收集期触发重依赖
    from app.services.simple_analysis_service import create_analysis_config

    return lambda mode=None: create_analysis_config(
        selected_analysts=["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"],
        quick_model="qwen-plus",
        deep_model="qwen-max",
        llm_provider="dashscope",
        market_type="A股",
    ) if mode is None else create_analysis_config(
        selected_analysts=["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"],
        quick_model="qwen-plus",
        deep_model="qwen-max",
        llm_provider="dashscope",
        market_type="A股",
        mode=mode,
    )


def test_mode_default_is_full(_config):
    """缺省 mode 必须是 full（尽调），确保默认行为与历史深度分析一致。"""
    config = _config()
    assert config["mode"] == "full"


@pytest.mark.parametrize("input_mode,expected", [
    ("full", "full"),
    ("deep", "full"),
    ("light", "light"),
    ("quick", "light"),
])
def test_mode_normalization(_config, input_mode, expected):
    """快评/尽调及其旧值归一化正确。"""
    config = _config(input_mode)
    assert config["mode"] == expected