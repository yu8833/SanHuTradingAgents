#!/usr/bin/env python3
"""
诊断Tushare返回空数据的原因
分析时间参数、股票代码、API限制等可能的问题

已迁移：从已删除的 tradingagents.dataflows.tushare_utils 迁移到直连 ts.pro_api()。
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import tushare as ts


def get_pro():
    """获取 Tushare pro API 实例（token 来自环境变量或 provider）"""
    try:
        from tradingagents.dataflows.providers.china.tushare import get_tushare_provider
        token = getattr(get_tushare_provider(), "token", None) or ""
    except Exception:
        token = ""
    if not token:
        token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        return None
    ts.set_token(token)
    return ts.pro_api()


def get_pro_or_die():
    """获取 pro 实例，未连接时打印并返回 None"""
    pro = get_pro()
    if pro is None:
        print("❌ Tushare未连接")
    return pro


def to_ts_code(symbol: str) -> str:
    """将 A股 6 位代码转换为 ts_code（6/9开头→SH，0/1/2/3开头→SZ，4/8开头→BJ）"""
    symbol = str(symbol).strip()
    if "." in symbol:  # 已是 ts_code 格式（如 000001.SZ）时直接返回
        return symbol
    if len(symbol) != 6 or not symbol.isdigit():
        return symbol
    if symbol.startswith(("6", "9")):
        suffix = "SH"
    elif symbol.startswith(("4", "8")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{symbol}.{suffix}"


def _get_daily(pro, symbol: str, start: str, end: str):
    """按日期范围获取日线数据（返回 DataFrame）"""
    start_compact = start.replace("-", "")
    end_compact = end.replace("-", "")
    return pro.daily(ts_code=to_ts_code(symbol), start_date=start_compact, end_date=end_compact)


def test_time_parameters():
    """测试不同的时间参数"""
    print("🕐 测试时间参数...")
    print("=" * 60)
    
    # 测试不同的时间范围
    test_cases = [
        {
            "name": "原始问题时间",
            "start": "2025-01-10", 
            "end": "2025-01-17"
        },
        {
            "name": "最近7天",
            "start": (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
            "end": datetime.now().strftime('%Y-%m-%d')
        },
        {
            "name": "最近30天", 
            "start": (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
            "end": datetime.now().strftime('%Y-%m-%d')
        },
        {
            "name": "2024年最后一周",
            "start": "2024-12-25",
            "end": "2024-12-31"
        },
        {
            "name": "2025年第一周",
            "start": "2025-01-01", 
            "end": "2025-01-07"
        }
    ]
    
    pro = get_pro_or_die()
    if pro is None:
        return
    
    symbol = "300033"  # 同花顺
    
    for case in test_cases:
        print(f"\n📅 {case['name']}: {case['start']} 到 {case['end']}")
        
        try:
            data = _get_daily(pro, symbol, case['start'], case['end'])
            
            if data is not None and not data.empty:
                print(f"   ✅ 获取成功: {len(data)}条数据")
                print(f"   📊 数据范围: {data['trade_date'].min()} 到 {data['trade_date'].max()}")
            else:
                print(f"   ❌ 返回空数据")
                
        except Exception as e:
            print(f"   ❌ 异常: {e}")


def test_stock_codes():
    """测试不同的股票代码"""
    print("\n📊 测试不同股票代码...")
    print("=" * 60)
    
    # 测试不同类型的股票
    test_symbols = [
        {"code": "300033", "name": "同花顺", "market": "创业板"},
        {"code": "000001", "name": "平安银行", "market": "深圳主板"},
        {"code": "600036", "name": "招商银行", "market": "上海主板"},
        {"code": "688001", "name": "华兴源创", "market": "科创板"},
        {"code": "002415", "name": "海康威视", "market": "深圳中小板"},
    ]
    
    pro = get_pro_or_die()
    if pro is None:
        return
    
    # 使用最近7天的数据
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    print(f"📅 测试时间范围: {start_date} 到 {end_date}")
    
    for symbol_info in test_symbols:
        symbol = symbol_info["code"]
        print(f"\n📈 {symbol} ({symbol_info['name']} - {symbol_info['market']})")
        
        try:
            data = _get_daily(pro, symbol, start_date, end_date)
            
            if data is not None and not data.empty:
                print(f"   ✅ 获取成功: {len(data)}条数据")
                # 显示最新一条数据
                latest = data.iloc[-1]
                print(f"   💰 最新价格: {latest['close']:.2f}")
            else:
                print(f"   ❌ 返回空数据")
                
        except Exception as e:
            print(f"   ❌ 异常: {e}")


def test_api_limits():
    """测试API限制和权限"""
    print("\n🔐 测试API限制和权限...")
    print("=" * 60)
    
    import time
    
    pro = get_pro_or_die()
    if pro is None:
        return
    
    # 测试基本信息获取（通常权限要求较低）
    print("📋 测试股票基本信息获取...")
    try:
        stock_list = pro.stock_basic(exchange='', list_status='L')
        if stock_list is not None and not stock_list.empty:
            print(f"   ✅ 股票列表获取成功: {len(stock_list)}只股票")
        else:
            print(f"   ❌ 股票列表为空")
    except Exception as e:
        print(f"   ❌ 股票列表获取失败: {e}")
    
    # 测试连续调用（检查频率限制）
    print("\n⏱️ 测试API调用频率...")
    symbol = "000001"
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    
    for i in range(3):
        print(f"   第{i+1}次调用...")
        start_time = time.time()
        
        try:
            data = _get_daily(pro, symbol, start_date, end_date)
            duration = time.time() - start_time
            
            if data is not None and not data.empty:
                print(f"   ✅ 成功: {len(data)}条数据，耗时: {duration:.2f}秒")
            else:
                print(f"   ❌ 空数据，耗时: {duration:.2f}秒")
                
        except Exception as e:
            duration = time.time() - start_time
            print(f"   ❌ 异常: {e}，耗时: {duration:.2f}秒")
        
        # 短暂延迟避免频率限制
        if i < 2:
            time.sleep(1)


def test_date_formats():
    """测试日期格式处理"""
    print("\n📅 测试日期格式处理...")
    print("=" * 60)
    
    # 测试不同的日期格式
    date_formats = [
        {"format": "YYYY-MM-DD", "start": "2025-01-10", "end": "2025-01-17"},
        {"format": "YYYYMMDD", "start": "20250110", "end": "20250117"},
    ]
    
    pro = get_pro_or_die()
    if pro is None:
        return
    
    symbol = "000001"
    
    for fmt in date_formats:
        print(f"\n📝 测试格式 {fmt['format']}: {fmt['start']} 到 {fmt['end']}")
        
        try:
            data = _get_daily(pro, symbol, fmt['start'], fmt['end'])
            
            if data is not None and not data.empty:
                print(f"   ✅ 获取成功: {len(data)}条数据")
            else:
                print(f"   ❌ 返回空数据")
                
        except Exception as e:
            print(f"   ❌ 异常: {e}")


def main():
    """主函数"""
    print("🔍 Tushare空数据问题诊断")
    print("=" * 80)
    
    # 1. 测试时间参数
    test_time_parameters()
    
    # 2. 测试股票代码
    test_stock_codes()
    
    # 3. 测试API限制
    test_api_limits()
    
    # 4. 测试日期格式
    test_date_formats()
    
    # 5. 总结
    print("\n📋 诊断总结")
    print("=" * 60)
    print("💡 可能的原因:")
    print("   1. 时间范围问题 - 查询的日期范围内没有交易数据")
    print("   2. 股票代码问题 - 股票代码格式不正确或股票已退市")
    print("   3. API权限问题 - Tushare账号权限不足")
    print("   4. 网络问题 - 网络连接不稳定")
    print("   5. 缓存问题 - 缓存了错误的空数据")
    print("   6. 交易日历 - 查询日期不是交易日")

if __name__ == "__main__":
    main()