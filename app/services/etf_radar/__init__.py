"""ETF Radar 服务：行业ETF资金流雷达。

基于 fund_etf_spot_em 全量ETF资金流 + stock_fund_flow_industry 行业资金流，
识别行业主题ETF，按资金流/动量/量能共振评分，输出 Top5 卡片 + 全排名表。
"""
from .etf_radar_service import EtfRadarService, get_etf_radar_service