#!/usr/bin/env python3
"""
测试增强的Tushare日志功能
验证详细日志是否能帮助追踪数据获取问题
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def test_enhanced_logging():
    """测试增强的日志功能"""
    print("🔍 测试增强的Tushare日志功能")
    print("=" * 80)

    try:
        from tradingagents.dataflows.a_stock import resolve_ticker
        from tradingagents.dataflows.interface import get_china_stock_info_unified

        # 测试用例1: 正常股票代码
        print("\n📊 测试用例1: 正常股票代码 (000001)")
        print("-" * 60)

        symbol = "000001"

        result = resolve_ticker(symbol)
        print(f"结果: {result}")
        info = get_china_stock_info_unified(symbol)
        print(f"统一信息: {info[:200] if info else 'None'}")

        # 测试用例2: 可能有问题的股票代码
        print("\n📊 测试用例2: 创业板股票 (300033)")
        print("-" * 60)

        symbol = "300033"

        result = resolve_ticker(symbol)
        print(f"结果: {result}")
        info = get_china_stock_info_unified(symbol)
        print(f"统一信息: {info[:200] if info else 'None'}")

        # 测试用例3: 可能不存在的股票代码
        print("\n📊 测试用例3: 可能不存在的股票代码 (999999)")
        print("-" * 60)

        symbol = "999999"

        result = resolve_ticker(symbol)
        print(f"结果: {result}")
        info = get_china_stock_info_unified(symbol)
        print(f"统一信息: {info[:200] if info else 'None'}")

        print("\n✅ 增强日志测试完成")
        print("📋 请查看日志文件以获取详细的调试信息")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_direct_tushare_provider():
    """直接测试Tushare Provider"""
    print("\n🔍 直接测试Tushare Provider")
    print("=" * 80)

    try:
        from app.services.basics_sync.utils import get_pro

        provider = get_pro()

        if provider is None:
            print("❌ Tushare未连接")
            return

        # 测试直接调用
        print(f"📊 直接调用Provider: 300033")
        data = provider.daily(ts_code="300033.SZ", start_date="20250110", end_date="20250117")

        if data is not None and not data.empty:
            print(f"✅ 直接调用成功: {len(data)}条数据")
            print(f"📊 数据列: {list(data.columns)}")
            print(f"📊 日期范围: {data['trade_date'].min()} 到 {data['trade_date'].max()}")
        else:
            print(f"❌ 直接调用返回空数据")

    except Exception as e:
        print(f"❌ 直接测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_adapter_layer():
    """测试适配器层"""
    print("\n🔍 测试适配器层")
    print("=" * 80)

    try:
        from app.services.data_sources.tushare_adapter import TushareAdapter

        adapter = TushareAdapter()

        if not adapter.is_available():
            print("❌ 适配器未连接")
            return

        # 测试适配器调用
        print(f"📊 调用适配器: 300033")
        data = adapter.get_kline("300033", period="day", limit=10)

        if data:
            print(f"✅ 适配器调用成功: {len(data)}条K线数据")
            print(f"📊 数据列: {list(data[0].keys()) if data else '无'}")
        else:
            print(f"❌ 适配器调用返回空数据")

    except Exception as e:
        print(f"❌ 适配器测试失败: {e}")
        import traceback
        traceback.print_exc()

def main():
    """主函数"""
    print("🧪 增强日志功能测试")
    print("=" * 80)
    print("📝 此测试将生成详细的日志信息，帮助追踪数据获取问题")
    print("📁 请查看 logs/tradingagents.log 文件获取完整日志")
    print("=" * 80)
    
    # 1. 测试增强日志功能
    test_enhanced_logging()
    
    # 2. 直接测试Provider
    test_direct_tushare_provider()
    
    # 3. 测试适配器层
    test_adapter_layer()
    
    print("\n📋 测试总结")
    print("=" * 60)
    print("✅ 增强日志功能测试完成")
    print("📊 现在每个数据获取步骤都有详细的日志记录")
    print("🔍 包括:")
    print("   - API调用前后的状态")
    print("   - 参数转换过程")
    print("   - 返回数据的详细信息")
    print("   - 异常的完整堆栈")
    print("   - 缓存操作的详细过程")
    print("📁 详细日志请查看: logs/tradingagents.log")

if __name__ == "__main__":
    main()
