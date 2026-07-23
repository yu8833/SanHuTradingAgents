# -*- coding: utf-8 -*-
"""
趋势交易分析器模块

从 daily_stock_analysis 移植，适配 TradingAgents-CN
"""

from .stock_analyzer import (
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
    BuySignal,
    MACDStatus,
    RSIStatus,
    analyze_stock,
)

__all__ = [
    'StockTrendAnalyzer',
    'TrendAnalysisResult',
    'TrendStatus',
    'VolumeStatus',
    'BuySignal',
    'MACDStatus',
    'RSIStatus',
    'analyze_stock',
]
