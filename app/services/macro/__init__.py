"""宏观快扫（盘前）数据与规则引擎。

模块划分（对应设计文档《第六章·交易工具与日常流程》§5 宏观快扫细化设计）：
  - financial_calendar.py  财经日历 provider（东财首选 → AKShare 兜底 → 手工高频事件日历）
  - news_classifier.py     快讯分级（重要性规则）
  - macro_scorer.py        规则引擎（方向/置信度/依据明细）
  - macro_service.py       编排：取数 → 评分 → LLM 解读 → 落库
"""
