"""ETF Radar 服务：行业ETF资金流雷达。

数据链路（方案B，已实测）：
  1. fund_etf_spot_em()            全量ETF资金流（~1575只，含主力净流入/超大单/大单/小单/量比/份额）
  2. stock_fund_flow_industry()    行业资金流（~90行业，净额/流入/流出，做行业交叉校验）
  3. 按名称关键词识别行业主题ETF（一行业多ETF取流通市值最大为代表）
  4. 按 ETF 主力净流入分位评分（资金为王，动量/量能仅展示不参与排序）→ Top5 卡片 + 全排名表
  5. 快照入库 MongoDB `etf_radar_snapshot`（按 as_of 留存），API 读最新快照（不阻塞网络）

注意：东财 stock_sector_fund_flow_rank 连接被拒，不可用；行业资金流统一走同花顺。
"""

from __future__ import annotations
from app.utils.timezone import now_tz

import asyncio
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from app.core.database import get_mongo_db
from app.services.data_sources.akshare_adapter import AKShareAdapter

logger = logging.getLogger(__name__)

# 资金为王：排名主依据为 ETF 主力净流入分位（动量/量能仅展示，不参与排序）
W_FUND = 1.0
W_MOM = 0.0
W_VOL = 0.0
# 一行业取代表ETF：按流通市值（元）取最大
# 行业资金流单位：同花顺 stock_fund_flow_industry 净额为亿元
_INDUSTRY_FLOW_UNIT = "亿元"

# 常用列名（东财 fund_etf_spot_em）
_COL_CODE = "代码"
_COL_NAME = "名称"
_COL_CLOSE = "最新价"
_COL_PCT = "涨跌幅"
_COL_FUND_NET = "主力净流入-净额"
_COL_FUND_NET_PCT = "主力净流入-净占比"
_COL_SUPER_LARGE = "超大单净流入-净额"
_COL_LARGE = "大单净流入-净额"
_COL_MEDIUM = "中单净流入-净额"
_COL_SMALL = "小单净流入-净额"
_COL_VOL_RATIO = "量比"
_COL_TURNOVER = "换手率"
_COL_SHARE = "最新份额"
_COL_FLOAT_MV = "流通市值"
_COL_TOTAL_MV = "总市值"
_COL_DATA_DATE = "数据日期"

# 同花顺行业资金流列名
_IND_COL_NAME = "行业"
_IND_COL_NET = "净额"
_IND_COL_INFLOW = "流入资金"
_IND_COL_OUTFLOW = "流出资金"
_IND_COL_PCT = "行业-涨跌幅"
_IND_COL_LEAD = "领涨股"


def _safe_float(v) -> float | None:
    try:
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return None
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v, ndigits: int = 4):
    f = _safe_float(v)
    if f is None:
        return None
    return round(f, ndigits)


def _percentile_rank(series: pd.Series) -> pd.Series:
    """0-1 分位排名（缺失值置于 0.5）。"""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return pd.Series(0.5, index=s.index)
    return s.rank(pct=True)


class EtfRadarService:
    """ETF Radar 服务：采集 → 识别 → 评分 → 排名 → 入库。"""

    def __init__(self):
        self._adapter = AKShareAdapter()

    # ---------- 数据采集 ----------
    async def _collect_raw(self) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        """并行采集 ETF 资金流 + 行业资金流（AKShare 同步调用放入线程池，避免阻塞事件循环）。"""
        etf_df, ind_df = await asyncio.gather(
            asyncio.to_thread(self._adapter.get_etf_spot_fund_flow),
            asyncio.to_thread(self._adapter.get_industry_fund_flow),
            return_exceptions=True,
        )
        if isinstance(etf_df, BaseException):
            logger.error(f"ETF 资金流采集失败: {etf_df}")
            etf_df = None
        if isinstance(ind_df, BaseException):
            logger.error(f"行业资金流采集失败: {ind_df}")
            ind_df = None
        return etf_df, ind_df

    # ---------- 识别 + 评分 ----------
    def _score(self, etf_df: pd.DataFrame) -> list[dict]:
        """识别行业ETF → 每行业取代表ETF → 资金流/动量/量能分位共振评分。"""
        from .industry_map import identify_industries

        if etf_df is None or etf_df.empty:
            return []

        names = etf_df[_COL_NAME].astype(str).tolist() if _COL_NAME in etf_df.columns else []
        name_to_industry = identify_industries(names)
        if not name_to_industry:
            logger.warning("ETF Radar: 未识别到任何行业主题ETF")
            return []

        df = etf_df.copy()
        df[_COL_NAME] = df[_COL_NAME].astype(str)
        df["_industry"] = df[_COL_NAME].map(name_to_industry)
        df = df[df["_industry"].notna()].copy()
        if df.empty:
            return []

        # 每行业取代表ETF：流通市值最大
        mv_col = _COL_FLOAT_MV if _COL_FLOAT_MV in df.columns else _COL_TOTAL_MV
        df[mv_col] = pd.to_numeric(df[mv_col], errors="coerce")
        df = df.sort_values(mv_col, ascending=False).drop_duplicates("_industry")

        # 分位评分
        df["_fund_pct"] = _percentile_rank(df[_COL_FUND_NET]) if _COL_FUND_NET in df.columns else 0.5
        df["_mom_pct"] = _percentile_rank(df[_COL_PCT]) if _COL_PCT in df.columns else 0.5
        df["_vol_pct"] = _percentile_rank(df[_COL_VOL_RATIO]) if _COL_VOL_RATIO in df.columns else 0.5

        items = []
        for _, r in df.iterrows():
            fund_score = round(float(r["_fund_pct"]) * 100, 2)
            mom_score = round(float(r["_mom_pct"]) * 100, 2)
            vol_score = round(float(r["_vol_pct"]) * 100, 2)
            # 资金为王：排名只由资金流分位决定，动量/量能仅展示、不参与排序
            composite = round(fund_score, 2)
            items.append({
                "industry": str(r["_industry"]),
                "etf_code": str(r.get(_COL_CODE) or "").strip(),
                "etf_name": str(r.get(_COL_NAME) or "").strip(),
                "close": _round(r.get(_COL_CLOSE)),
                "pct_chg": _round(r.get(_COL_PCT), 2),
                "fund_net_inflow": _round(r.get(_COL_FUND_NET)),
                "fund_net_inflow_pct": _round(r.get(_COL_FUND_NET_PCT), 2),
                "super_large_inflow": _round(r.get(_COL_SUPER_LARGE)),
                "large_inflow": _round(r.get(_COL_LARGE)),
                "medium_inflow": _round(r.get(_COL_MEDIUM)),
                "small_inflow": _round(r.get(_COL_SMALL)),
                "volume_ratio": _round(r.get(_COL_VOL_RATIO), 2),
                "turnover_rate": _round(r.get(_COL_TURNOVER), 2),
                "share": _round(r.get(_COL_SHARE)),
                "float_mv": _round(r.get(_COL_FLOAT_MV)),
                "total_mv": _round(r.get(_COL_TOTAL_MV)),
                "fund_flow_score": fund_score,
                "momentum_score": mom_score,
                "volume_score": vol_score,
                "composite_score": composite,
                "sector_net_inflow": None,   # 由行业资金流交叉校验填充
                "sector_pct_chg": None,
            })

        items.sort(key=lambda x: x["composite_score"], reverse=True)
        return items

    @staticmethod
    def _industry_flows(ind_df: pd.DataFrame) -> list[dict]:
        """整理行业资金流（同花顺），供行业交叉校验展示。"""
        if ind_df is None or ind_df.empty:
            return []
        flows = []
        for _, r in ind_df.iterrows():
            flows.append({
                "industry": str(r.get(_IND_COL_NAME) or "").strip(),
                "net_inflow": _round(r.get(_IND_COL_NET), 2),
                "inflow": _round(r.get(_IND_COL_INFLOW), 2),
                "outflow": _round(r.get(_IND_COL_OUTFLOW), 2),
                "pct_chg": _round(r.get(_IND_COL_PCT), 2),
                "lead_stock": str(r.get(_IND_COL_LEAD) or "").strip(),
            })
        return flows

    @staticmethod
    def _attach_industry_flows(items: list[dict], flows: list[dict]) -> None:
        """把行业资金流交叉校验到代表ETF（行业名做模糊匹配，未匹配则为空）。"""
        if not flows:
            return
        for it in items:
            ind = it.get("industry", "")
            matched = None
            for f in flows:
                if f.get("industry") == ind or (ind and ind in f.get("industry", "")):
                    matched = f
                    break
            if matched:
                it["sector_net_inflow"] = matched.get("net_inflow")
                it["sector_pct_chg"] = matched.get("pct_chg")

    # ---------- 入库 ----------
    async def collect_and_save(self) -> dict:
        """采集 → 评分 → 快照入库 MongoDB（etf_radar_snapshot，按 as_of 覆盖）。"""
        etf_df, ind_df = await self._collect_raw()
        if etf_df is None or etf_df.empty:
            logger.error("ETF Radar: ETF 资金流为空，跳过入库")
            return {"success": False, "message": "ETF 资金流采集失败", "items": []}

        items = self._score(etf_df)
        flows = self._industry_flows(ind_df)
        self._attach_industry_flows(items, flows)

        # as_of：优先取 ETF 数据日期（YYYY-MM-DD → YYYYMMDD），否则取今天
        as_of = now_tz().strftime("%Y%m%d")
        if _COL_DATA_DATE in etf_df.columns:
            d = str(etf_df[_COL_DATA_DATE].iloc[0]).replace("-", "")[:8]
            if len(d) == 8 and d.isdigit():
                as_of = d

        now_iso = now_tz().isoformat(timespec="seconds")
        doc = {
            "as_of": as_of,
            "updated_at": now_iso,
            "industry_count": len(items),
            "items": items,
            "industry_flows": flows,
            "source": "akshare",
        }
        try:
            db = get_mongo_db()
            await db["etf_radar_snapshot"].replace_one(
                {"as_of": as_of}, doc, upsert=True)
            logger.info(f"✅ ETF Radar 快照已入库: as_of={as_of}, 行业数={len(items)}")
        except Exception as e:
            logger.error(f"ETF Radar 快照入库失败: {e}")

        return {"success": True, "as_of": as_of, "industry_count": len(items),
                "items": items, "industry_flows": flows}

    # ---------- 查询 ----------
    async def get_summary(self, top_n: int = 5, refresh: bool = False) -> dict:
        """返回 ETF Radar 摘要：Top5 卡片 + 全排名表。

        默认读 MongoDB 最新快照（快速，无网络）。refresh=True 或快照为空时触发实时采集。
        """
        if refresh:
            return await self.refresh_summary(top_n)

        db = get_mongo_db()
        latest = None
        try:
            latest = await db["etf_radar_snapshot"].find_one(
                sort=[("as_of", -1), ("updated_at", -1)])
        except Exception as e:
            logger.warning(f"ETF Radar 读快照失败（尝试实时采集）: {e}")

        if not latest or not latest.get("items"):
            logger.info("ETF Radar: 无快照，触发实时采集")
            return await self.refresh_summary(top_n)

        return self._build_response(latest, top_n)

    async def refresh_summary(self, top_n: int = 5) -> dict:
        """强制实时采集并返回摘要。"""
        result = await self.collect_and_save()
        if not result.get("success"):
            return {"success": False, "message": result.get("message", "采集失败"),
                    "as_of": "", "updated_at": "", "top": [], "rankings": [], "industry_count": 0}
        latest = {"as_of": result["as_of"], "items": result["items"],
                  "industry_flows": result.get("industry_flows", [])}
        return self._build_response(latest, top_n)

    @staticmethod
    def _build_response(latest: dict, top_n: int) -> dict:
        items = latest.get("items", []) or []
        rankings = sorted(items, key=lambda x: x.get("composite_score", 0), reverse=True)
        return {
            "success": True,
            "as_of": latest.get("as_of", ""),
            "updated_at": latest.get("updated_at", ""),
            "industry_count": latest.get("industry_count", len(items)),
            "top": rankings[:top_n],
            "rankings": rankings,
            "industry_flows": latest.get("industry_flows", []),
        }


_service: EtfRadarService | None = None


def get_etf_radar_service() -> EtfRadarService:
    global _service
    if _service is None:
        _service = EtfRadarService()
    return _service
