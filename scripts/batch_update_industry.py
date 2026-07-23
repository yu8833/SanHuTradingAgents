#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量更新股票行业信息
从 akshare stock_individual_info_em 获取每只股票的所属行业
并更新到 stock_basic_info 集合
"""
import sys
import time
import traceback
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo import MongoClient

# 配置
MONGO_URI = "mongodb://admin:tradingagents123@mongodb:27017/tradingagentscn?authSource=admin"
DB_NAME = "tradingagentscn"
COLLECTION = "stock_basic_info"

try:
    import akshare as ak
except ImportError:
    print("❌ akshare 未安装，请先运行: pip install akshare")
    sys.exit(1)


def now():
    return datetime.now(timezone.utc)


def _sanitize(val, default):
    if val is None:
        return default
    if isinstance(val, float):
        import math
        if math.isnan(val) or math.isinf(val):
            return default
    s = str(val).strip()
    if not s or s.lower() in ("none", "nan", "null", "未知", "unknown", "-", "--"):
        return default
    return s


def get_industry_for_code(code: str) -> dict:
    """获取单个股票的行业信息"""
    result = {"code": code, "industry": "", "area": "", "list_date": "", "success": False}
    try:
        info_df = ak.stock_individual_info_em(symbol=code)
        if info_df is None or info_df.empty:
            return result

        item_dict = dict(zip(info_df["item"].astype(str), info_df["value"].astype(str)))

        result["industry"] = _sanitize(item_dict.get("所属行业", ""), "")
        result["area"] = _sanitize(item_dict.get("所属地区", ""), "")
        result["list_date"] = _sanitize(item_dict.get("上市时间", ""), "")
        result["success"] = True

        name = _sanitize(item_dict.get("股票简称", ""), "")
        if name:
            result["name"] = name

    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    print("=" * 60)
    print("🔄 开始批量更新股票行业信息")
    print("=" * 60)

    # 连接数据库
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[DB_NAME]
        collection = db[COLLECTION]
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        sys.exit(1)

    # 获取需要更新的股票
    total_count = collection.count_documents({"source": "akshare"})
    need_update = list(
        collection.find(
            {
                "source": "akshare",
                "$or": [
                    {"industry": {"$exists": False}},
                    {"industry": None},
                    {"industry": ""},
                    {"industry": "未知"},
                ],
            },
            {"_id": 1, "code": 1, "name": 1, "industry": 1, "area": 1, "list_date": 1},
        )
    )

    print(f"\n📊 akshare 源总股票数: {total_count}")
    print(f"🔍 需要更新行业信息的股票: {len(need_update)}")

    if not need_update:
        print("✅ 没有需要更新的股票，退出")
        client.close()
        return

    # 分批处理，避免超时
    batch_size = 200
    max_workers = 5
    all_to_update = need_update

    updated_count = 0
    failed_count = 0
    error_messages = {}

    print(f"\n⚙️ 配置: 批大小={batch_size}, 并发线程={max_workers}")
    print(f"⏰ 预计时间: 约 {len(all_to_update) // (batch_size * max_workers) + 1} 分钟")
    print()

    # 按批次处理
    for batch_start in range(0, len(all_to_update), batch_size):
        batch = all_to_update[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = len(all_to_update) // batch_size + 1

        print(f"📦 处理第 {batch_num}/{total_batches} 批 ({len(batch)} 只股票)")

        # 并发获取行业信息
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(get_industry_for_code, stock["code"]): stock
                for stock in batch
            }
            for future in as_completed(futures):
                try:
                    res = future.result(timeout=30)
                    results.append(res)
                except Exception as e:
                    stock = futures[future]
                    failed_count += 1
                    err_msg = str(e)
                    error_messages[err_msg] = error_messages.get(err_msg, 0) + 1

        # 汇总更新
        bulk_ops = []
        for res in results:
            if not res.get("success"):
                failed_count += 1
                if "error" in res:
                    error_messages[res["error"]] = error_messages.get(res["error"], 0) + 1
                continue

            update_fields = {"updated_at": now()}
            has_update = False

            # 只在有有效信息时更新
            if res.get("industry") and res["industry"] not in ("", "未知"):
                update_fields["industry"] = res["industry"]
                has_update = True

            if res.get("area") and res["area"] not in ("", "未知"):
                update_fields["area"] = res["area"]
                has_update = True

            if res.get("list_date") and res["list_date"] not in ("", "未知"):
                update_fields["list_date"] = res["list_date"]
                has_update = True

            if res.get("name") and res["name"].startswith("股票"):
                # 如果当前名称是"股票xxx"格式，而获取到了真实名称，则更新
                existing = next((s for s in batch if s["code"] == res["code"]), None)
                if existing and (not existing.get("name") or existing["name"].startswith("股票")):
                    update_fields["name"] = res["name"]
                    has_update = True

            if has_update:
                bulk_ops.append(
                    {
                        "update_one": {
                            "filter": {"code": res["code"], "source": "akshare"},
                            "update": {"$set": update_fields},
                        }
                    }
                )

        # 执行批量更新
        if bulk_ops:
            try:
                r = collection.bulk_write(bulk_ops)
                updated_count += r.modified_count
                print(f"   ✅ 本批更新: {r.modified_count} 只")
            except Exception as e:
                print(f"   ⚠️ 本批更新失败: {e}")

        # 速率限制，避免过快请求
        if batch_start + batch_size < len(all_to_update):
            time.sleep(1.5)

    # 结果统计
    print("\n" + "=" * 60)
    print("📊 最终结果")
    print("=" * 60)
    print(f"✅ 成功更新行业信息: {updated_count} 只")
    print(f"❌ 获取失败: {failed_count} 只")

    if error_messages:
        print(f"\n⚠️ 错误类型统计 (前5):")
        sorted_errors = sorted(error_messages.items(), key=lambda x: x[1], reverse=True)[:5]
        for err, count in sorted_errors:
            print(f"  {err[:60]}: {count} 次")

    # 查看最终行业分布
    print("\n📋 行业分布前20:")
    pipeline = [
        {"$match": {"source": "akshare", "industry": {"$exists": True, "$nin": [None, "", "未知"]}}},
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    for doc in list(collection.aggregate(pipeline)):
        print(f"  {doc['_id']}: {doc['count']}")

    has_valid_industry = collection.count_documents(
        {"source": "akshare", "industry": {"$exists": True, "$nin": [None, "", "未知"]}}
    )
    print(f"\n📊 有效行业: {has_valid_industry}/{total_count} ({has_valid_industry * 100 // max(total_count,1)}%)")

    client.close()
    print("\n✅ 行业信息更新完成!")


if __name__ == "__main__":
    main()
