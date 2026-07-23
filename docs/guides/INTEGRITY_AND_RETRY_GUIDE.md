# 数据完整性、重试策略、辩论收敛度和准确性守护者使用指南

## 一、数据完整性检查模块

### 1.1 概述

`tradingagents.agents.utils.data_integrity` 模块提供了对分析师执行过程中数据完整性的监控和评估。

### 1.2 核心组件

#### DataIntegrityEvaluator - 单个分析师完整性评估器

```python
from tradingagents.agents.utils.data_integrity import DataIntegrityEvaluator, DataAvailability

# 创建评估器
evaluator = DataIntegrityEvaluator("market")  # 技术分析师

# 记录工具调用结果
evaluator.record_success("get_indicators", "返回成功数据...")
evaluator.record_failure("get_stock_data", "连接超时", DataAvailability.TIMEOUT)
evaluator.record_empty_result("get_news")  # 返回空结果

# 评估完整性
report = evaluator.assess_integrity()
print(f"完整性级别: {report.quality_label}")  # 高质量/中等质量/低质量
print(f"核心工具成功率: {report.core_success_rate:.1%}")
print(f"是否可以继续: {report.can_proceed}")
```

#### BatchIntegrityManager - 批量分析师管理器

```python
from tradingagents.agents.utils.data_integrity import BatchIntegrityManager

# 创建批量管理器
manager = BatchIntegrityManager()

# 为每个分析师获取评估器
market_evaluator = manager.get_evaluator("market")
news_evaluator = manager.get_evaluator("news")

# 记录调用...

# 评估所有分析师
manager.assess_all()

# 获取整体质量评分
score, label = manager.get_overall_quality()
print(f"整体质量: {score:.1%} ({label})")

# 判断是否可以进入辩论阶段
can_proceed, reason = manager.should_proceed_to_debate()
print(f"可进入辩论: {can_proceed}, 原因: {reason}")

# 生成摘要报告
summary = manager.generate_summary_report()
print(summary)
```

### 1.3 完整性级别

| 级别 | 说明 | 建议操作 |
|------|------|----------|
| COMPLETE | 所有核心数据可用 | 正常分析 |
| PARTIAL | 部分数据缺失 | 继续但降低置信度 |
| CRITICAL_MISSING | 核心数据缺失>50% | 警告，结论仅供参考 |
| COMPLETE_FAILURE | 完全失败 | 建议重试或使用缓存 |

### 1.4 在并行分析师中的集成

修改后的 `parallel_analysts.py` 已自动集成数据完整性检查：

```python
# 分析完成后，state 中会包含以下字段：
results = {
    "market_report": "...",  # 分析师报告
    "_data_quality_summary": "...",  # 数据质量摘要
    "_can_proceed_to_debate": True,  # 是否可进入辩论
    "_debate_proceed_reason": "",    # 原因说明
    "_overall_quality_score": 0.85,  # 整体质量评分
}
```

---

## 二、LLM统一重试策略模块

### 2.1 概述

`tradingagents.llm_clients.retry_strategy` 模块提供了标准化的重试机制。

### 2.2 核心组件

#### RetryConfig - 重试配置

```python
from tradingagents.llm_clients.retry_strategy import (
    RetryConfig,
    RetryStrategy,
    get_retry_config,
)

# 自定义配置
config = RetryConfig(
    max_retries=3,                    # 最多重试3次
    base_delay=1.0,                   # 基础延迟1秒
    max_delay=60.0,                    # 最大延迟60秒
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,  # 指数退避
    jitter=True,                       # 启用抖动
    jitter_factor=0.5,               # 抖动范围 ±50%
    request_timeout=60.0,             # 单次请求超时60秒
)
```

#### 预设配置模式

```python
from tradingagents.llm_clients.retry_strategy import get_retry_config

# 默认配置
config = get_retry_config("default")

# 快速模式（少重试，快失败）
fast_config = get_retry_config("fast")

# 保守模式（多重试，长等待）
conservative_config = get_retry_config("conservative")

# 限流友好模式（专门处理429错误）
rate_limit_config = get_retry_config("rate_limit_friendly")
```

### 2.3 使用方式

#### 方式1：直接使用 RetryableLLMCaller

```python
import asyncio
from tradingagents.llm_clients.retry_strategy import RetryableLLMCaller, get_retry_config

async def example():
    caller = RetryableLLMCaller(get_retry_config("default"))

    # 调用任何异步 LLM 函数
    result = await caller.call(llm.invoke, prompt)

    # 查看统计
    print(f"重试统计: {caller.stats.to_dict()}")
    # {'total_attempts': 3, 'success_rate': '100.0%', 'retry_rate': '66.7%', ...}

asyncio.run(example())
```

#### 方式2：装饰器方式

```python
from tradingagents.llm_clients.retry_wrapper import with_llm_retry

class MyLLMClient:
    @with_llm_retry(mode="conservative")
    async def call(self, prompt: str) -> str:
        return await self.llm.invoke(prompt)

client = MyLLMClient()
result = await client.call("分析这只股票")
```

#### 方式3：包装器方式

```python
from tradingagents.llm_clients.retry_wrapper import wrap_llm_with_retry

# 包装现有 LLM
retrying_llm = wrap_llm_with_retry(
    base_llm=original_llm,
    mode="rate_limit_friendly"
)

# 使用方式与原 LLM 完全相同
result = await retrying_llm.invoke(prompt)
```

---

## 三、辩论收敛度判断模块

### 3.1 概述

`tradingagents.agents.utils.debate_convergence` 模块用于评估辩论过程中的观点收敛情况，避免无意义的过长辩论。

### 3.2 核心组件

#### DebateConvergenceEvaluator - 辩论收敛度评估器

```python
from tradingagents.agents.utils.debate_convergence import (
    DebateConvergenceEvaluator,
    DebatePhase,
)

# 创建评估器
evaluator = DebateConvergenceEvaluator(
    phase=DebatePhase.INVESTMENT_DEBATE,  # 投资辩论
    max_rounds=5,
    min_rounds=2,
    convergence_threshold=0.7,
)

# 分析辩论轮次
analysis = evaluator.analyze_round(state, round_number=1)

# 评估收敛度
report = evaluator.assess_convergence()
print(f"收敛级别: {report.convergence_level.value}")
print(f"收敛分数: {report.convergence_score:.2f}")
print(f"是否应该停止: {report.should_stop}")
print(f"停止原因: {report.stop_reason}")
```

#### DebateConvergenceManager - 辩论收敛管理器

```python
from tradingagents.agents.utils.debate_convergence import DebateConvergenceManager

# 创建管理器
manager = DebateConvergenceManager(
    max_investment_rounds=5,
    max_risk_rounds=5,
    min_rounds=2,
)

# 判断是否继续投资辩论
should_continue, next_node, report = manager.should_continue_investment_debate(state)

# 判断是否继续风控辩论
should_continue, next_node, report = manager.should_continue_risk_debate(state)

# 生成摘要
summary = manager.generate_summary()
```

### 3.3 收敛级别

| 级别 | 说明 | 处理方式 |
|------|------|----------|
| CONVERGED | 观点已收敛 | 停止辩论 |
| NARROWING | 观点正在收敛 | 可继续几轮 |
| STABLE | 观点差异稳定 | 达到最大轮次后停止 |
| DIVERGING | 观点分歧扩大 | 关注新论据 |
| FATIGUE | 辩论疲劳 | 立即停止 |

### 3.4 在 ConditionalLogic 中的集成

```python
# 辩论判断逻辑已集成到 conditional_logic.py
# 自动进行收敛度评估并记录日志：
# 📊 投资辩论收敛度: converged, 分数: 0.85, 轮次: 3
# ✅ 投资辩论终止: 观点已收敛（收敛分数: 0.85）
```

---

## 四、准确性守护者节点

### 4.1 概述

`tradingagents.agents.guardians.accuracy_guardian` 模块在最终决策生成前进行质量把关。

### 4.2 核心组件

#### AccuracyGuardian - 准确性守护者

```python
from tradingagents.agents.guardians.accuracy_guardian import AccuracyGuardian

# 创建守护者
guardian = AccuracyGuardian(
    data_quality_weight=0.4,      # 数据质量权重
    debate_quality_weight=0.3,    # 辩论质量权重
    risk_consistency_weight=0.3,  # 风控一致性权重
)

# 评估结论质量
report = guardian.assess_conclusion_quality(
    state=agent_state,
    integrity_reports=batch_manager._reports,
    debate_reports=convergence_manager._reports,
)

# 查看结果
print(f"整体质量: {report.quality_grade.value}")
print(f"置信度: {report.confidence_level.value}")
print(f"是否应该信任: {report.should_trust}")
print(f"原因: {report.trust_reason}")
```

### 4.3 质量等级和置信度

| 质量等级 | 分数范围 | 置信度 | 建议 |
|----------|----------|--------|------|
| A（优秀） | ≥85% | 高 | 可作为决策参考 |
| B（良好） | 70-85% | 中等 | 可参考但需关注风险 |
| C（一般） | 50-70% | 低 | 仅供参考，需验证 |
| D（较差） | 30-50% | 很低 | 不建议直接用于决策 |
| F（很差） | <30% | 不可靠 | 建议重新分析 |

### 4.4 在 TradingGraph 中的集成

```
流程变化：
Portfolio Manager -> Accuracy Guardian -> END

Accuracy Guardian 会生成以下 state 字段：
- _accuracy_guardian_report: 完整报告对象
- _quality_grade: 质量等级（优秀/良好/一般/较差/很差）
- _confidence_level: 置信度（高/中等/低/很低/不可靠）
- _overall_quality_score: 整体质量分数
- _should_trust: 是否应该信任此结论
- _trust_reason: 原因说明
```

### 4.5 将质量报告融入最终决策

```python
from tradingagents.agents.guardians.accuracy_guardian import enhance_final_decision_with_quality

# 在最终决策前添加质量评估摘要
enhanced_decision = enhance_final_decision_with_quality(
    final_decision=original_decision,
    guardian_report=report,
)
```

---

## 五、完整流程图

```
                    ┌─────────────────────┐
                    │   Parallel Analysts │
                    │   (数据完整性检查)   │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │    Quality Gate     │
                    └─────────────────────┘
                              │
                              ▼
           ┌──────────────────────────────────┐
           │     Investment Debate Loop       │
           │   (辩论收敛度判断)                │
           │   Bull <-> Bear                  │
           └──────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   Research Manager  │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │       Trader        │
                    └─────────────────────┘
                              │
                              ▼
           ┌──────────────────────────────────┐
           │     Risk Debate Loop             │
           │   (辩论收敛度判断)                │
           │   Aggressive <-> Conservative <-> Neutral │
           └──────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Portfolio Manager  │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Accuracy Guardian  │  ← 新增节点
                    │  (质量评估+置信度)   │
                    └─────────────────────┘
                              │
                              ▼
                           [ END ]
```

---

## 六、最佳实践总结

### 6.1 数据完整性

1. 区分核心和非核心工具失败
2. 在关键决策点检查完整性
3. 记录完整性报告便于问题排查

### 6.2 重试策略

1. 选择合适的模式（fast/default/conservative）
2. 配置合理的超时
3. 监控重试统计

### 6.3 辩论收敛度

1. 设置最小轮次避免过早终止
2. 关注疲劳检测避免结论漂移
3. 收敛分数达标可提前终止

### 6.4 准确性守护者

1. 数据质量是最关键的因素
2. 置信度低于"低"时应谨慎决策
3. 警告信息应认真阅读

---

## 七、日志示例

```
2024-01-15 10:30:00 [INFO] 🚀 开始并行执行 7 位分析师
2024-01-15 10:30:05 [INFO] ✅ [market] 分析完成, 完整性: 高质量
2024-01-15 10:30:08 [WARNING] 🔶 [news] 部分数据缺失
2024-01-15 10:30:10 [INFO] 📊 整体数据质量: 良好
2024-01-15 10:30:15 [INFO] 📊 投资辩论收敛度: narrowing, 分数: 0.75, 轮次: 2
2024-01-15 10:30:25 [INFO] 📊 投资辩论收敛度: converged, 分数: 0.85, 轮次: 3
2024-01-15 10:30:25 [INFO] ✅ 投资辩论终止: 观点已收敛（收敛分数: 0.85）
2024-01-15 10:30:35 [INFO] 📊 风控辩论收敛度: stable, 分数: 0.65, 轮次: 2
2024-01-15 10:30:45 [INFO] 📊 风控辩论收敛度: narrowing, 分数: 0.72, 轮次: 3
2024-01-15 10:30:50 [INFO] 🔍 Accuracy Guardian 正在评估结论质量...
2024-01-15 10:30:50 [INFO] 📊 质量评估完成: ✅ 整体质量: 良好 (分数: 75%, 置信度: 中等置信度)
```
