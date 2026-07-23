import sys
import asyncio
sys.path.insert(0, '/Users/yupeng/stock/TradingAgents-CN')

from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service
import logging

logging.basicConfig(level=logging.INFO)

svc = get_three_buys_three_sells_service()

params = {
    "start_date": "2026-01-01",
    "end_date": "2026-07-05",
    "hold_days": 60,
    "initial_capital": 1000000,
    "top_n": 10,
    "max_position_pct": 0.15,
    "min_score": 0,
    "bias_b1_min": -30.0,
    "bias_b1_max": -20.0,
    "breakout_volume_ratio": 1.5,
    "zhongyang_threshold": 0.05,
    "pullback_bias_range": 5,
    "s2_break_days": 2,
    "enable_dg_filter": True,
    "enable_safety_net": True,
    "enable_slow_group_s1": True,
    "enable_gmma_filter": True,
    "enable_overheat_filter": True,
    "enable_market_matrix": True,
    "enable_adaptive_volume": True,
    "enable_strict_b1": True,
    "limit": 50,
}

async def main():
    result = await svc.backtest(params)
    
    print(f"\n{'='*60}")
    print(f"总交易笔数: {result['total_trades']}")
    print(f"总收益: {result['total_return']}%")
    print(f"最大回撤: {result['max_drawdown']}%")
    print(f"胜率: {result['win_rate']}%")
    print(f"平均收益: {result['avg_return']}%")
    print(f"期末资金: {result['final_capital']}")
    print(f"初始资金: {result['initial_capital']}")
    
    print(f"\n最差20笔交易:")
    for i, t in enumerate(result['worst_trades']):
        print(f"  {i+1}. {t['code']} {t['name']} {t['signal_type']} {t['buy_date']}->{t['sell_date']} "
              f"收益: {t['return_pct']}% 卖出原因: {t['sell_reason']} 股数: {t['shares']} 利润: {t['profit']}")
    
    print(f"\n每日结果 (前20天):")
    for i, d in enumerate(result['daily_results'][:20]):
        print(f"  {d['date']}: 总资产 {d['total_value']:.0f} 收益 {d['return_pct']:+.2f}% 回撤 {d['drawdown']:.2f}% 持仓 {d['position_count']}只")
    
    print(f"\n每日结果 (回撤最大的几天):")
    sorted_daily = sorted(result.get('daily_results', []), key=lambda x: x['drawdown'], reverse=True)[:10]
    for d in sorted_daily:
        print(f"  {d['date']}: 总资产 {d['total_value']:.0f} 收益 {d['return_pct']:+.2f}% 回撤 {d['drawdown']:.2f}% 持仓 {d['position_count']}只")

asyncio.run(main())
