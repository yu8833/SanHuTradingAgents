
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量填充股票基础信息（含行业）
用于新部署后快速填充数据库中的股票基础数据和行业分类
"""
import sys
import traceback
from datetime import datetime, timezone
from pymongo import MongoClient, errors
import akshare as ak

# 配置
MONGO_URI = "mongodb://admin:tradingagents123@mongodb:27017/tradingagentscn?authSource=admin"
DB_NAME = "tradingagentscn"
COLLECTION = "stock_basic_info"

def now():
    return datetime.now()

def main():
    print("=" * 60)
    print("🔄 开始批量填充股票基础信息")
    print("=" * 60)

    # 连接数据库
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DB_NAME]
        collection = db[COLLECTION]
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        sys.exit(1)

    # 检查现有数据
    existing_count = collection.count_documents({"source": "akshare"})
    print(f"📊 现有 akshare 源股票数: {existing_count}")

    # 如果有旧数据，清理掉
    if existing_count > 0:
        print(f"🧹 清理旧的 akshare 数据...")
        del_result = collection.delete_many({"source": "akshare"})
        print(f"   已删除 {del_result.deleted_count} 条记录")

    # 开始收集股票信息
    all_docs = []
    seen_codes = set()

    def add_doc(code, name, industry, market):
        if not code or code in seen_codes:
            return
        seen_codes.add(code)
        clean_industry = (industry or "").strip()
        if not clean_industry or clean_industry.lower() in ("none", "nan", "null"):
            clean_industry = "未知"
        clean_name = (name or "").strip() or f"股票{code}"
        all_docs.append({
            "code": code,
            "name": clean_name,
            "area": "未知",
            "industry": clean_industry,
            "market": market,
            "list_date": "",
            "source": "akshare",
            "full_symbol": code,
            "market_info": "",
            "last_sync": now(),
            "sync_status": "success",
            "created_at": now(),
            "updated_at": now()
        })

    # 1. 深交所A股
    print("\n1. 拉取深交所A股列表...")
    try:
        sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
        print(f"   深交所: {len(sz_df)} 只")
        for _, row in sz_df.iterrows():
            code = str(row.get("A股代码", "")).zfill(6)
            industry_raw = str(row.get("所属行业", "")).strip()
            name = str(row.get("A股简称", "")).strip()
            industry = "未知"
            if industry_raw and " " in industry_raw:
                parts = industry_raw.split(" ", 1)
                if len(parts) == 2:
                    industry = parts[1]
            elif industry_raw:
                industry = industry_raw
            add_doc(code, name, industry, "深交所")
    except Exception as e:
        print(f"   ⚠️ 深交所接口失败: {e}")
        traceback.print_exc()

    # 2. 上交所主板
    print("\n2. 拉取上交所主板...")
    try:
        sh_df = ak.stock_info_sh_name_code(symbol="主板A股")
        print(f"   上交所主板: {len(sh_df)} 只")
        for _, row in sh_df.iterrows():
            code = str(row.get("证券代码", "")).zfill(6)
            name = str(row.get("证券简称", "")).strip()
            add_doc(code, name, "未知", "上交所")
    except Exception as e:
        print(f"   ⚠️ 上交所接口失败: {e}")

    # 3. 科创板
    print("\n3. 拉取科创板...")
    try:
        kcb_df = ak.stock_info_sh_name_code(symbol="科创板")
        print(f"   科创板: {len(kcb_df)} 只")
        for _, row in kcb_df.iterrows():
            code = str(row.get("证券代码", "")).zfill(6)
            name = str(row.get("证券简称", "")).strip()
            add_doc(code, name, "未知", "科创板")
    except Exception as e:
        print(f"   ⚠️ 科创板接口失败: {e}")

    # 4. 创业板
    print("\n4. 拉取创业板...")
    try:
        cyb_df = ak.stock_info_sz_name_code(symbol="创业板列表")
        print(f"   创业板: {len(cyb_df)} 只")
        for _, row in cyb_df.iterrows():
            code = str(row.get("A股代码", "")).zfill(6)
            industry_raw = str(row.get("所属行业", "")).strip()
            name = str(row.get("A股简称", "")).strip()
            industry = "未知"
            if industry_raw and " " in industry_raw:
                parts = industry_raw.split(" ", 1)
                if len(parts) == 2:
                    industry = parts[1]
            elif industry_raw:
                industry = industry_raw
            add_doc(code, name, industry, "创业板")
    except Exception as e:
        print(f"   ⚠️ 创业板接口失败: {e}")

    print(f"\n📊 共收集 {len(all_docs)} 条记录")

    # 批量插入
    if not all_docs:
        print("❌ 没有获取到任何股票数据")
        client.close()
        sys.exit(1)

    print(f"\n💾 开始批量插入 {len(all_docs)} 条记录...")
    try:
        result = collection.insert_many(all_docs, ordered=False)
        print(f"✅ 成功插入 {len(result.inserted_ids)} 条记录")
    except errors.BulkWriteError as bwe:
        print(f"⚠️ 部分写入失败，成功: {len(bwe.details.get('insertedIds', {}))}")
    except Exception as e:
        print(f"❌ 批量插入失败: {e}")
        traceback.print_exc()

    # 统计最终结果
    total = collection.count_documents({"source": "akshare"})
    has_industry = collection.count_documents({
        "source": "akshare",
        "industry": {"$exists": True, "$nin": [None, "", "未知"]}
    })
    unknown_industry = collection.count_documents({
        "source": "akshare",
        "industry": {"$in": [None, "", "未知"]}
    })

    print("\n" + "=" * 60)
    print("📊 结果统计")
    print("=" * 60)
    print(f"akshare 总数: {total}")
    print(f"有有效行业: {has_industry}")
    print(f"行业未知/空: {unknown_industry}")

    # 行业分布
    print("\n📋 行业分布前15:")
    pipeline = [
        {"$match": {"source": "akshare", "industry": {"$exists": True, "$nin": [None, "", "未知"]}}},
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 15}
    ]
    for doc in list(collection.aggregate(pipeline)):
        print(f"  {doc['_id']}: {doc['count']}")

    print("\n✅ 股票基础信息填充完成!")
    client.close()


if __name__ == "__main__":
    main()
