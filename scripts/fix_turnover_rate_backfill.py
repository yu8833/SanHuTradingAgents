"""
一次性脚本：从 Tushare daily_basic 回补 market_quotes 的 turnover_rate。

因 Tushare rt_k 不返回换手率，此前 _bulk_upsert 会用 None 覆盖
AKShare 已写入的 turnover_rate，导致看板「活跃换手」永远为空。
"""
import logging
import os
import sys
from datetime import datetime

# 兼容容器内运行：脚本位于 /tmp 时，手动把应用根目录加进 sys.path
_APP_DIR = "/app" if os.path.isdir("/app/app") else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# 显式加载 .env
from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_mongo_db_sync
from app.services.data_sources.tushare_adapter import TushareAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fix_turnover")

# 获取最新交易日
adapter = TushareAdapter()
if not adapter.is_available():
    logger.error("Tushare 不可用，退出")
    sys.exit(1)

# 从 MongoDB 获取最新 trade_date
db = get_mongo_db_sync()
latest_mq = db["market_quotes"].find_one({}, {"trade_date": 1}, sort=[("trade_date", -1)])
trade_date = (latest_mq or {}).get("trade_date", "")
if not trade_date:
    logger.error("market_quotes 为空，无法确定交易日")
    sys.exit(1)

logger.info(f"最新 market_quotes trade_date: {trade_date}")

# 查询 Tushare daily_basic（格式 YYYYMMDD，但 Tushare 需要 YYYYMMDD）
td = str(trade_date).replace("-", "")
logger.info(f"查询 Tushare daily_basic, trade_date={td}")
df = adapter.get_daily_basic(td)
if df is None or df.empty:
    logger.error(f"Tushare daily_basic 未返回数据")
    sys.exit(1)

# 构建 code -> turnover_rate 映射
tr_map: dict[str, float] = {}
for _, row in df.iterrows():
    ts_code = str(row.get("ts_code") or "")
    tr = row.get("turnover_rate")
    if tr is not None and ts_code and "." in ts_code:
        code6 = ts_code.split(".")[0].zfill(6)
        tr_map[code6] = float(tr)

logger.info(f"Tushare 返回 {len(df)} 条，含 turnover_rate: {len(tr_map)} 条")

# 批量更新 market_quotes（幂等：仅设置非空值，不覆盖其他字段）
bulk_ops = []
from pymongo import UpdateOne

for code, tr in tr_map.items():
    bulk_ops.append(
        UpdateOne(
            {"code": code},
            {"$set": {"turnover_rate": tr, "updated_at": datetime.now()}},
        )
    )

if bulk_ops:
    result = db["market_quotes"].bulk_write(bulk_ops, ordered=False)
    logger.info(f"更新完成: matched={result.matched_count}, modified={result.modified_count}")
else:
    logger.info("无需要更新的记录")

# 验证
after = db["market_quotes"].count_documents({"turnover_rate": {"$ne": None}})
logger.info(f"回补后 market_quotes 中 turnover_rate 非空数量: {after}")