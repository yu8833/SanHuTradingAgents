#!/usr/bin/env python3
"""
调试 Tushare 数据格式
检查 stock_basic 和 daily_basic 的实际数据格式和代码匹配问题

已迁移：从已删除的 tradingagents.dataflows.tushare_utils 迁移到直连 ts.pro_api()。
"""
import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

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
        print("❌ 未获取到 TUSHARE_TOKEN，Tushare 未连接")
        return None
    import tushare as ts
    ts.set_token(token)
    return ts.pro_api()

def debug_tushare_data():
    """调试 Tushare 数据格式"""
    print("🔍 调试 Tushare 数据格式")
    print("=" * 60)
    
    pro = get_pro()
    if pro is None:
        return False
    
    try:
        # 1. 检查 stock_basic 数据格式
        print("📊 检查 stock_basic 数据格式:")
        print("-" * 40)
        
        stock_df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
        if stock_df is not None and not stock_df.empty:
            print(f"股票总数: {len(stock_df)}")
            print("前5条记录的关键字段:")
            for i, (_, row) in enumerate(stock_df.head().iterrows()):
                ts_code = row.get("ts_code", "N/A")
                symbol = row.get("symbol", "N/A")
                name = row.get("name", "N/A")
                print(f"  {i+1}. ts_code: {ts_code}, symbol: {symbol}, name: {name}")
        else:
            print("❌ stock_basic 返回空或失败")

        # 2. 检查 daily_basic 数据格式
        print("\n📊 检查 daily_basic 数据格式:")
        print("-" * 40)
        
        # 找到最近的交易日
        today = datetime.now()
        db_df = None
        for i in range(10):  # 最多回溯10天
            trade_date = (today - timedelta(days=i)).strftime("%Y%m%d")
            try:
                # 只获取前10条记录用于调试
                db_df = pro.daily_basic(trade_date=trade_date, fields="ts_code,total_mv,circ_mv,pe,pb,turnover_rate")
                if db_df is not None and not db_df.empty:
                    print(f"交易日期: {trade_date}")
                    print(f"daily_basic 记录数: {len(db_df)}")
                    print("前5条记录:")
                    for j, (_, row) in enumerate(db_df.head().iterrows()):
                        ts_code = row.get("ts_code", "N/A")
                        total_mv = row.get("total_mv", "N/A")
                        pe = row.get("pe", "N/A")
                        pb = row.get("pb", "N/A")
                        print(f"  {j+1}. ts_code: {ts_code}, total_mv: {total_mv}, pe: {pe}, pb: {pb}")
                    break
            except Exception as e:
                print(f"  {trade_date}: 无数据或错误 - {e}")
                continue
        
        # 3. 检查代码匹配问题
        print("\n🔍 检查代码匹配问题:")
        print("-" * 40)
        
        # 检查平安银行的不同代码格式
        test_codes = ["000001.SZ", "1.SZ", "000001", "1"]
        
        if db_df is not None and not db_df.empty:
            print("在 daily_basic 中查找平安银行:")
            for code in test_codes:
                matches = db_df[db_df['ts_code'] == code] if 'ts_code' in db_df.columns else []
                if len(matches) > 0:
                    print(f"  ✅ 找到 {code}: {len(matches)} 条记录")
                    row = matches.iloc[0]
                    print(f"     total_mv: {row.get('total_mv', 'N/A')}, pe: {row.get('pe', 'N/A')}")
                else:
                    print(f"  ❌ 未找到 {code}")
            
            # 显示所有包含 "000001" 或 "1" 的记录
            print("\n所有可能相关的记录:")
            for _, row in db_df.iterrows():
                ts_code = str(row.get("ts_code", ""))
                if "000001" in ts_code or ts_code in ["1.SZ", "1.SH"]:
                    print(f"  {ts_code}: total_mv={row.get('total_mv', 'N/A')}, pe={row.get('pe', 'N/A')}")
        
        print("\n✅ 调试完成!")
        return True
        
    except Exception as e:
        print(f"❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = debug_tushare_data()
    exit(0 if success else 1)