#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补充股票行业信息（通过东方财富行业成分股）
策略：
1. 从 akshare 获取行业列表
2. 按行业获取成分股
3. 建立代码->行业映射
4. 批量更新数据库中 industry 为空/None/"未知" 的记录
"""
import sys
import time
import os
from datetime import datetime, timezone
from pymongo import MongoClient, UpdateOne

try:
    import akshare as ak
except ImportError:
    print("❌ akshare 未安装，请先执行: pip install akshare")
    sys.exit(1)

MONGO_URI = os.environ.get(
    "TRADINGAGENTS_MONGO_URL",
    "mongodb://admin:tradingagents123@localhost:27017/tradingagentscn?authSource=admin"
)
DB_NAME = "tradingagentscn"
COLLECTION = "stock_basic_info"


def now():
    return datetime.now(timezone.utc)


def main():
    print("=" * 70)
    print("🔄 批量补充股票行业信息")
    print("=" * 70)

    # 连接数据库
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[DB_NAME]
        collection = db[COLLECTION]
        print(f"✅ 数据库连接成功: {MONGO_URI}")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        sys.exit(1)

    # 统计当前状态
    total_count = collection.count_documents({})
    empty_industry_count = collection.count_documents(
        {"industry": {"$in": [None, "", "未知"]}}
    )
    valid_industry_count = collection.count_documents(
        {"industry": {"$exists": True, "$nin": [None, "", "未知"]}}
    )
    print(f"\n📊 总股票数: {total_count}")
    print(f"📊 已有有效行业: {valid_industry_count}")
    print(f"📊 需要补充行业: {empty_industry_count}")

    # 获取行业列表
    print("\n1️⃣  获取行业分类列表...")
    try:
        ind_names = ak.stock_board_industry_name_em()
        print(f"   ✅ 获取到 {len(ind_names)} 个行业分类")
    except Exception as e:
        print(f"   ❌ 行业列表获取失败: {e}")
        client.close()
        sys.exit(1)

    # 确定行业名称列
    industry_col = None
    for col in ["板块名称", "行业", "名称"]:
        if col in ind_names.columns:
            industry_col = col
            break

    if industry_col is None:
        print(f"   ❌ 找不到行业名称列，可用列: {list(ind_names.columns)}")
        client.close()
        sys.exit(1)

    # 遍历行业，获取成分股 -> 建立 code->industry 映射
    code_to_industry = {}
    industry_stats = {}
    error_count = 0

    print("\n2️⃣  遍历行业获取成分股...")
    for idx, row in ind_names.iterrows():
        industry_name = str(row[industry_col]).strip()
        if not industry_name:
            continue

        max_retries = 3
        success = False
        for attempt in range(max_retries):
            try:
                cons = ak.stock_board_industry_cons_em(symbol=industry_name)
                if cons is not None and not cons.empty:
                    # 找到代码列
                    code_col = None
                    for col in ["代码", "股票代码", "证券代码"]:
                        if col in cons.columns:
                            code_col = col
                            break
                    if code_col:
                        count = 0
                        for _, c_row in cons.iterrows():
                            # 规范化代码：取后6位
                            raw_code = str(c_row[code_col]).strip()
                            # 去除可能的.SH/.SZ后缀
                            if "." in raw_code:
                                raw_code = raw_code.split(".")[0]
                            # 补零到6位
                            c = raw_code.zfill(6)
                            if len(c) >= 6:
                                c = c[-6:]
                            if c:
                                code_to_industry[c] = industry_name
                                count += 1
                        industry_stats[industry_name] = count
                        print(f"   [{idx+1}/{len(ind_names)}] {industry_name}: {count} 只")
                    else:
                        print(f"   ⚠️  {industry_name}: 找不到代码列 {list(cons.columns)}")
                success = True
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
                else:
                    print(f"   ❌ {industry_name}: 失败 ({e})")
                    error_count += 1

        time.sleep(0.5)  # 限制请求速率

    print(f"\n📊 总共映射 {len(code_to_industry)} 个代码的行业信息")
    print(f"📊 失败行业数: {error_count}")

    # 找出需要更新的股票
    print("\n3️⃣  匹配需要更新的股票...")
    need_update = []
    for doc in collection.find(
        {"industry": {"$in": [None, "", "未知"]}},
        {"code": 1, "name": 1}
    ):
        code = doc.get("code", "")
        if code in code_to_industry:
            need_update.append((code, code_to_industry[code]))

    print(f"📊 可以更新 {len(need_update)} 只股票")

    # 批量更新
    if not need_update:
        print("\n✅ 没有需要更新的股票，数据库行业数据可能已很完整")
        client.close()
        return

    print(f"\n4️⃣  开始批量更新数据库...")
    bulk_ops = []
    for code, industry in need_update:
        bulk_ops.append(
            UpdateOne(
                {"code": code, "source": "akshare"},
                {
                    "$set": {
                        "industry": industry,
                        "updated_at": now(),
                    }
                }
            )
        )

    print(f"   准备 {len(bulk_ops)} 条更新操作")

    # 分批执行
    batch_size = 500
    updated_total = 0
    for i in range(0, len(bulk_ops), batch_size):
        batch = bulk_ops[i:i + batch_size]
        try:
            result = collection.bulk_write(batch)
            updated_total += result.modified_count
            print(f"   第 {i // batch_size + 1} 批: 已更新 {result.modified_count}/{len(batch)} 条")
        except Exception as e:
            print(f"   第 {i // batch_size + 1} 批失败: {e}")

    # 最终统计
    final_empty = collection.count_documents(
        {"industry": {"$in": [None, "", "未知"]}}
    )
    final_valid = collection.count_documents(
        {"industry": {"$exists": True, "$nin": [None, "", "未知"]}}
    )

    print("\n" + "=" * 70)
    print("📊 更新完成统计")
    print("=" * 70)
    print(f"  有有效行业: {final_valid} (原为 {valid_industry_count})")
    print(f"  无行业数据: {final_empty} (原为 {empty_industry_count})")
    print(f"  本次更新数: {updated_total}")

    print("\n📋 行业分布Top30:")
    pipeline = [
        {"$match": {"industry": {"$exists": True, "$nin": [None, "", "未知"]}}},
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 30},
    ]
    for doc in list(collection.aggregate(pipeline)):
        print(f"  {doc['_id']}: {doc['count']}")

    client.close()
    print("\n✅ 任务完成!")


if __name__ == "__main__":
    main()
