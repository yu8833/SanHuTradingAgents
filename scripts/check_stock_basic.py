import os
from pymongo import MongoClient

mongo_uri = os.environ.get(
    "TRADINGAGENTS_MONGODB_URL",
    "mongodb://admin:tradingagents123@mongodb:27017/tradingagentscn?authSource=admin",
)
client = MongoClient(mongo_uri)
db = client["tradingagentscn"]

# 直接查 stock_basic_info
sbi = db["stock_basic_info"]
total = sbi.estimated_document_count()
print(f"stock_basic_info 总记录数: {total}")

if total > 0:
    print("\n前3条记录:")
    for doc in sbi.find().limit(3):
        print(f"  {doc}")

    has_industry = sbi.count_documents(
        {"industry": {"$exists": True, "$ne": None, "$ne": "", "$ne": "未知"}}
    )
    print(f"\n有有效industry: {has_industry}")

    pipeline = [
        {"$match": {"industry": {"$exists": True, "$ne": None, "$ne": "", "$ne": "未知"}}},
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    results = list(sbi.aggregate(pipeline))
    print(f"\n行业分布:")
    for r in results:
        print(f"  {r['_id']}: {r['count']} 条")

    # 检查 source 字段
    print("\n=== source 字段分布 ===")
    pipeline2 = [
        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    for r in sbi.aggregate(pipeline2):
        print(f"  {r['_id']}: {r['count']} 条")

# 看看有没有其他相关集合
print("\n=== 尝试其他可能的集合 ===")
try:
    for col in ["stocks", "stock_info", "stock_list", "basic_info"]:
        c = db[col].estimated_document_count()
        print(f"  {col}: {c} 条")
except Exception as e:
    print(f"  错误: {e}")

# 检查 data_source_configs
print("\n=== data_source_configs ===")
try:
    dsc = db["data_source_configs"]
    if dsc.estimated_document_count() > 0:
        for doc in dsc.find():
            api_key = doc.get("api_key", "")
            has_token = "有" if api_key and api_key != "your-tushare-token" else "无/占位"
            print(f"  源: {doc.get('source_id')}, 启用: {doc.get('enabled')}, token: {has_token}")
    else:
        print("  无配置")
except Exception as e:
    print(f"  错误: {e}")
