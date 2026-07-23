import os
from pymongo import MongoClient

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

print("\n=== stock_basic_info ===")
sbi = db["stock_basic_info"]
total = sbi.count_documents({})
print(f"总记录数: {total}")

if total > 0:
    print("\n前5条:")
    for doc in sbi.find().limit(5):
        print(f"  {doc}")

    has_industry = sbi.count_documents(
        {"industry": {"$exists": True, "$ne": None, "$ne": "", "$ne": "未知"}}
    )
    print(f"\n有有效industry: {has_industry}")

    print("\n行业分布(前20):")
    pipeline = [
        {"$match": {"industry": {"$exists": True, "$ne": None, "$ne": "", "$ne": "未知"}}},
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    results = list(sbi.aggregate(pipeline))
    for r in results:
        print(f"  {r['_id']}: {r['count']} 条")

print("\n=== 其他有industry的集合:")
for col in db.list_collection_names():
    c = db[col].count_documents({"industry": {"$exists": True, "$ne": None, "$ne": ""}})
    if c > 0:
        print(f"  {col}: {c} 条")

print("\n=== 检查数据源配置:")
dsc = db["data_source_configs"]
if dsc.count_documents({}) > 0:
    for doc in dsc.find():
        print(f"  源: {doc.get('source_id')}, 启用: {doc.get('enabled')}, token: {'有' if doc.get('api_key') and doc.get('api_key') != 'your-tushare-token' else '无/占位'}")
