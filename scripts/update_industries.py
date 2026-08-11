"""
批量获取股票行业信息并更新数据库
"""
import asyncio
import sys
import os
from datetime import datetime

# 添加项目路径
sys.path.insert(0, '/app')

import akshare as ak
import pandas as pd
from motor.motor_asyncio import AsyncIOMotorClient


async def get_industry_from_szse():
    """从深交所接口获取行业信息"""
    print("📊 从深交所接口获取行业信息...")
    try:
        sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
        if sz_df is None or sz_df.empty:
            print("  ⚠️ 深交所接口返回空")
            return {}

        # 建立 代码 -> 行业 映射
        industry_map = {}
        for _, row in sz_df.iterrows():
            code = str(row.get('A股代码', ''))
            industry = str(row.get('所属行业', '')).strip()
            if code and industry:
                # 简化行业名称，去掉前面的分类字母如 "C 制造业" -> "制造业"
                if ' ' in industry:
                    industry = industry.split(' ', 1)[1]
                industry_map[code] = industry

        print(f"  ✅ 深交所获取到 {len(industry_map)} 只股票的行业信息")

        # 统计行业分布
        from collections import Counter
        industries = list(industry_map.values())
        top_industries = Counter(industries).most_common(10)
        print(f"  前10个行业: {top_industries}")

        return industry_map
    except Exception as e:
        print(f"  ❌ 深交所接口失败: {type(e).__name__}: {str(e)[:80]}")
        return {}


async def get_industry_from_shse():
    """尝试从上交所接口获取行业信息（通常没有，但检查是否有备用方式）"""
    print("📊 从上交所接口获取行业信息...")
    try:
        # 上交所接口没有行业字段，但我们可以用其他方式
        # 先尝试 stock_zh_a_spot_em（有行业字段但不稳定）
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            cols = df.columns.tolist()
            # 查找行业字段
            industry_col = None
            for col in cols:
                if '行业' in str(col):
                    industry_col = col
                    break

            if industry_col:
                industry_map = {}
                for _, row in df.iterrows():
                    code = str(row.get('代码', '')).zfill(6)
                    industry = str(row.get(industry_col, '')).strip()
                    if code and industry and industry != 'nan':
                        industry_map[code] = industry
                print(f"  ✅ 从行情接口获取到 {len(industry_map)} 只股票的行业信息")
                return industry_map
            else:
                print(f"  ⚠️ 行情接口没有行业字段，字段为: {cols[:10]}")
        else:
            print("  ⚠️ 行情接口返回空")
    except Exception as e:
        print(f"  ❌ 行情接口失败: {type(e).__name__}: {str(e)[:80]}")

    return {}


async def update_industry_in_db():
    """更新数据库中的行业信息"""
    print("=" * 60)
    print("🔄 开始更新股票行业信息")
    print("=" * 60)

    # 连接数据库
    mongo_url = os.environ.get('MONGODB_URI', 'mongodb://admin:tradingagents123@mongodb:27017/')
    db_name = os.environ.get('MONGODB_DB', 'tradingagentscn')
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    collection = db['stock_basic_info']

    # 获取行业信息
    sz_industries = await get_industry_from_szse()

    # 尝试其他接口获取更多行业信息
    other_industries = await get_industry_from_shse()

    # 合并行业信息（后面的覆盖前面的）
    all_industries = {}
    all_industries.update(sz_industries)
    all_industries.update(other_industries)

    if not all_industries:
        print("❌ 无法获取任何行业信息")
        return

    print(f"\n📊 共获取 {len(all_industries)} 只股票的行业信息")

    # 获取数据库中的所有股票
    total_docs = await collection.count_documents({'source': 'akshare'})
    print(f"\n📊 数据库中共有 {total_docs} 只 akshare 源的股票")

    # 批量更新
    updated = 0
    skipped = 0
    batch_size = 100

    cursor = collection.find({'source': 'akshare'}, {'code': 1, 'industry': 1, 'name': 1})
    async for doc in cursor:
        code = str(doc.get('code', '')).zfill(6)
        current_industry = str(doc.get('industry', '')).strip()

        if code in all_industries:
            new_industry = all_industries[code]

            # 只有当没有行业或者行业变化时才更新
            if not current_industry or current_industry == "未知" or current_industry != new_industry:
                await collection.update_one(
                    {'_id': doc['_id']},
                    {'$set': {
                        'industry': new_industry,
                        'updated_at': datetime.now()
                    }}
                )
                updated += 1
            else:
                skipped += 1
        else:
            skipped += 1

    print(f"\n✅ 更新完成:")
    print(f"   更新行业信息: {updated} 只")
    print(f"   跳过: {skipped} 只")

    # 统计更新后的行业分布
    print(f"\n📊 数据库中行业分布 (前15):")
    pipeline = [
        {'$match': {'source': 'akshare', 'industry': {'$exists': True, '$ne': ''}}},
        {'$group': {'_id': '$industry', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': 15}
    ]
    async for stat in collection.aggregate(pipeline):
        print(f"   {stat['_id']}: {stat['count']} 只")

    client.close()
    print("\n🎉 行业信息更新完成!")


if __name__ == '__main__':
    asyncio.run(update_industry_in_db())
