import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient

try:
    mongo_uri = os.environ.get(
        "TRADINGAGENTS_MONGODB_URL",
        "mongodb://admin:tradingagents123@mongodb:27017/tradingagentscn?authSource=admin",
    )
    client = MongoClient(mongo_uri)
    db = client["tradingagentscn"]

    print("=== 集合列表 ===")
    for col in db.list_collection_names():
        count = db[col].count_documents({})
        print(f"  {col}: {count} 条")

    print("\n=== stock_basic_info 数据检查 ===")
    sbi = db["stock_basic_info"]
    total = sbi.count_documents({})
    print(f"总记录数: {total}")

    if total > 0:
        print("\n前5条记录:")
        for doc in sbi.find().limit(5):
            print(f"  {doc}")

        print("\n=== industry 字段检查 ===")
        has_industry = sbi.count_documents(
            {"industry": {"$exists": True, "$ne": None, "$ne": "", "$ne": "未知"}}
        )
        print(f"有有效industry字段的记录: {has_industry}")

        print("\n=== industry字段值分布(前30) ===")
        pipeline = [
            {
                "$match": {
                    "industry": {"$exists": True, "$ne": None, "$ne": "", "$ne": "未知"}
                }
            },
            {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 30},
        ]
        for result in sbi.aggregate(pipeline):
            print(f"  {result['_id']}: {result['count']} 条")

    print("\n=== 检查其他可能有行业数据的集合 ===")
    for col in db.list_collection_names():
        col_ref = db[col]
        has_ind = col_ref.count_documents(
            {"industry": {"$exists": True, "$ne": None, "$ne": ""}}
        )
        if has_ind > 0:
            print(f"  {col}: {has_ind} 条有 industry 字段")

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
