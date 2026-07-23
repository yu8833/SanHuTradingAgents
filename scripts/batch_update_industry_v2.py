#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量更新股票行业信息 (v2 - 使用行业成分股接口)
策略：
1. 从 akshare 获取行业列表
2. 按行业获取成分股
3. 批量更新数据库
"""
import sys
import time
from datetime import datetime, timezone
from pymongo import MongoClient, UpdateOne

try:
    import akshare as ak
except ImportError:
    print("❌ akshare 未安装")
    sys.exit(1)

MONGO_URI = "mongodb://admin:tradingagents123@mongodb:27017/tradingagentscn?authSource=admin"
DB_NAME = "tradingagentscn"
COLLECTION = "stock_basic_info"


def now():
    return datetime.now(timezone.utc)


def main():
    print("=" * 60)
    print("🔄 开始批量更新股票行业信息 (v2)")
    print("=" * 60)

    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[DB_NAME]
        collection = db[COLLECTION]
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        sys.exit(1)

    total_count = collection.count_documents({"source": "akshare"})
    print(f"\n📊 总股票数: {total_count}")

    # 策略1: 从东方财富行业分类获取
    # 获取行业列表
    code_to_industry = {}
    industry_stats = {}

    print("\n1️⃣  获取行业分类列表...")
    try:
        ind_names = ak.stock_board_industry_name_em()
        print(f"   获取到 {len(ind_names)} 个行业分类")

        industry_col = None
        for col in ["板块名称", "行业", "名称"]:
            if col in ind_names.columns:
                industry_col = col
                break

        if industry_col:
            for _, row in ind_names.iterrows():
                industry_name = str(row[industry_col]).strip()
                if not industry_name:
                    continue
                print(f"\n2️⃣  获取行业: {industry_name}")

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        cons = ak.stock_board_industry_cons_em(symbol=industry_name)
                        if cons is not None and not cons.empty:
                            code_col = None
                            for col in ["代码", "股票代码", "证券代码"]:
                                if col in cons.columns:
                                    code_col = col
                                    break
                            if code_col:
                                count = 0
                                for _, c_row in cons.iterrows():
                                    c = str(c_row[code_col]).zfill(6)
                                    if len(c) >= 6:
                                        c = c[-6:]  # 取后6位
                                    code_to_industry[c] = industry_name
                                    count += 1
                                industry_stats[industry_name] = count
                                print(f"   ✅ {count} 只")
                            else:
                                print(f"   ⚠️ 找不到代码列: {list(cons.columns)}")
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            time.sleep(2)
                        else:
                            print(f"   ⚠️ 失败: {e}")

                time.sleep(0.8)
        else:
            print(f"   ⚠️ 找不到行业名称列: {list(ind_names.columns)}")
    except Exception as e:
        print(f"   ⚠️ 行业列表获取失败: {e}")

    print(f"\n📊 从行业成分股获取到 {len(code_to_industry)} 个代码->行业映射")

    # 策略2: 如果行业成分股获取到的数据不够，尝试获取股票列表补充
    if len(code_to_industry) < 2000:
        print("\n3️⃣  补充从股票列表获取行业信息...")
        try:
            # 深交所主板
            sz_main = ak.stock_info_sz_name_code(symbol="A股列表")
            if sz_main is not None and not sz_main.empty:
                for _, row in sz_main.iterrows():
                    c = str(row.get("A股代码", "")).zfill(6)
                    ind_raw = str(row.get("所属行业", "")).strip()
                    if ind_raw and " " in ind_raw:
                        parts = ind_raw.split(" ", 1)
                        if len(parts) == 2:
                            ind_raw = parts[1]
                    if c and ind_raw and ind_raw not in ("", "nan", "NaN"):
                        if c not in code_to_industry:
                            code_to_industry[c] = ind_raw
                print(f"   深交所主板补充: {len(sz_main)} 只")
        except Exception as e:
            print(f"   深交所主板失败: {e}")

        # 创业板
        try:
            cyb = ak.stock_info_sz_name_code(symbol="创业板列表")
            if cyb is not None and not cyb.empty:
                for _, row in cyb.iterrows():
                    c = str(row.get("A股代码", "")).zfill(6)
                    ind_raw = str(row.get("所属行业", "")).strip()
                    if ind_raw and " " in ind_raw:
                        parts = ind_raw.split(" ", 1)
                        if len(parts) == 2:
                            ind_raw = parts[1]
                    if c and ind_raw and ind_raw not in ("", "nan", "NaN"):
                        if c not in code_to_industry:
                            code_to_industry[c] = ind_raw
                print(f"   创业板补充: {len(cyb)} 只")
        except Exception as e:
            print(f"   创业板失败: {e}")

    print(f"\n📊 总共获取到 {len(code_to_industry)} 个代码的行业信息")

    # 批量更新数据库
    if not code_to_industry:
        print("❌ 没有获取到任何行业信息")
        client.close()
        return

    print("\n4️⃣  开始批量更新数据库...")
    bulk_ops = []
    for code, industry in code_to_industry.items():
        bulk_ops.append(
            UpdateOne(
                {"code": code, "source": "akshare"},
                {
                    "$set": {
                        "industry": industry,
                        "updated_at": now(),
                    }
                },
            )
        )

    print(f"   准备更新 {len(bulk_ops)} 条记录")

    # 分批执行
    batch_size = 500
    updated_total = 0
    for i in range(0, len(bulk_ops), batch_size):
        batch = bulk_ops[i : i + batch_size]
        try:
            r = collection.bulk_write(batch)
            updated_total += r.modified_count
            print(f"   第 {i // batch_size + 1} 批: 更新 {r.modified_count}/{len(batch)} 条")
        except Exception as e:
            print(f"   第 {i // batch_size + 1} 批失败: {e}")

    # 结果统计
    has_valid_industry = collection.count_documents(
        {"source": "akshare", "industry": {"$exists": True, "$nin": [None, "", "未知"]}}
    )
    print("\n" + "=" * 60)
    print("📊 结果统计")
    print("=" * 60)
    print(f"总股票数: {total_count}")
    print(f"有有效行业信息: {has_valid_industry} ({has_valid_industry * 100 // max(total_count, 1)}%)")
    print(f"本次更新数: {updated_total}")

    print("\n📋 行业分布前30:")
    pipeline = [
        {
            "$match": {
                "source": "akshare",
                "industry": {"$exists": True, "$nin": [None, "", "未知"]},
            }
        },
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 30},
    ]
    for doc in list(collection.aggregate(pipeline)):
        print(f"  {doc['_id']}: {doc['count']}")

    client.close()
    print("\n✅ 完成!")


if __name__ == "__main__":
    main()
