"""资讯雷达数据层 —— 移植自 investment-news。

抓 12 赛道 108 个公开 RSS 源 → 合规过滤（赌/预测市场/加密/色情）+ 最近 N 天
+ 按赛道分组、时间倒序。纯标准库 + 线程池，零 key、零个股字段。

AI「今日要点」不在此模块——复用 Vibe-Research 的可插拔 AI 层（前端调 /api/chat，
把某赛道资讯打包给用户自己的模型提炼）。本模块只出客观资讯。

缓存策略：Redis + 本地文件二级缓存，TTL 5分钟（news级）。
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, "news_sources.json")
CACHE_DIR = os.path.join(HERE, ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "radar.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BEIJING = timezone(timedelta(hours=8))


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _parse_dt(s: str):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fetch_source(src: dict, per: int, cutoff, redline: list[str]):
    """抓单个 RSS 源；返回 items 列表，出错返回 None。"""
    try:
        req = urllib.request.Request(src["url"], headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=3) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        out = []
        for n in [e for e in root.iter() if _local(e.tag) in ("item", "entry")]:
            if len(out) >= per:
                break
            d = {"title": "", "url": "", "time": "", "ts": 0, "summary": "", "source": src["name"]}
            rawtime = ""
            for c in n:
                t = _local(c.tag)
                if t == "title" and not d["title"]:
                    d["title"] = (c.text or "").strip()
                elif t == "link" and not d["url"]:
                    d["url"] = c.get("href") or (c.text or "").strip()
                elif t in ("pubDate", "published", "updated", "date") and not rawtime:
                    rawtime = (c.text or "").strip()
                elif t in ("description", "summary", "content") and not d["summary"]:
                    d["summary"] = _strip_html(c.text or "")[:160]
            if not d["title"]:
                continue
            blob = (d["title"] + " " + d["summary"]).lower()
            if any(k in blob for k in redline):
                continue
            dt = _parse_dt(rawtime)
            if dt is not None:
                if cutoff and dt < cutoff:
                    continue
                d["time"] = dt.astimezone(BEIJING).strftime("%m-%d %H:%M")
                d["ts"] = int(dt.timestamp())
            else:
                d["time"] = "—"
            out.append(d)
        return out
    except Exception:
        return None


def _has_content(data: dict | None) -> bool:
    """判断雷达数据是否含实际资讯条目（避免全空结果被当作有效缓存）。"""
    if not data:
        return False
    return any(ind.get("items") for ind in data.get("industries") or [])


def fetch_radar() -> dict:
    """抓全部源，返回 12 赛道数据并落盘缓存。"""
    # 修复：使用 with 语句确保文件句柄正确关闭
    with open(SOURCES_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    days = cfg.get("fetch", {}).get("recent_days", 7)
    per = cfg.get("fetch", {}).get("per_source", 6)
    cutoff = datetime.now(BEIJING) - timedelta(days=days)
    redline = [k.lower() for k in cfg.get("redline_keywords", [])]

    byhint: dict[str, list] = {}
    for s in cfg["sources"]:
        byhint.setdefault(s["hint"], []).append(s)

    industries, tasks = [], []
    for i, ind in enumerate(cfg["industries"]):
        pool = byhint.get(ind["key"], [])
        industries.append({"key": ind["key"], "name": ind["name"], "accent": ind["accent"], "total": len(pool), "items": []})
        for s in pool:
            tasks.append((i, s))

    import concurrent.futures
    import time
    max_workers = min(20, len(tasks))
    overall_timeout = 15
    start_time = time.time()

    results = []
    ex = ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_to_task = {ex.submit(lambda t, ps=per, cf=cutoff, rl=redline: (t[0], _fetch_source(t[1], ps, cf, rl)), task): task for task in tasks}
        
        remaining = list(future_to_task.keys())
        while remaining and (time.time() - start_time) < overall_timeout:
            try:
                done, remaining = concurrent.futures.wait(remaining, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    try:
                        results.append(future.result())
                    except Exception:
                        continue
            except Exception:
                break
    finally:
        ex.shutdown(wait=False)

    failed = 0
    for idx, items in results:
        if items is None:
            failed += 1
            continue
        industries[idx]["items"].extend(items)
    for ind in industries:
        ind["items"].sort(key=lambda x: x.get("ts", 0), reverse=True)

    data = {
        "generated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        "recent_days": days,
        "industries": industries,
        "stats": {"industries": len(cfg["industries"]), "total_sources": len(cfg["sources"]), "failed_sources": failed},
    }
    # 仅当抓取到实际内容时才落盘，避免网络故障把已有的好缓存覆盖成空数据。
    if _has_content(data):
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)
    return data


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def skeleton() -> dict:
    """无缓存时返回赛道骨架（空 items），前端提示点刷新。"""
    # 修复：使用 with 语句确保文件句柄正确关闭
    with open(SOURCES_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    byhint: dict[str, int] = {}
    for s in cfg["sources"]:
        byhint[s["hint"]] = byhint.get(s["hint"], 0) + 1
    return {
        "generated_at": None,
        "recent_days": cfg.get("fetch", {}).get("recent_days", 7),
        "industries": [{"key": i["key"], "name": i["name"], "accent": i["accent"], "total": byhint.get(i["key"], 0), "items": []} for i in cfg["industries"]],
        "stats": {"industries": len(cfg["industries"]), "total_sources": len(cfg["sources"])},
    }


def get_radar(force: bool = False) -> dict:
    if force:
        return fetch_radar()
    cached = load_cache()
    if cached:
        return cached
    # 无缓存时自动抓取，避免前端看到空数据
    try:
        return fetch_radar()
    except Exception:
        return skeleton()


async def get_radar_cached(force: bool = False) -> dict:
    """带Redis缓存的资讯雷达读取：Redis → 本地文件缓存 →（后台线程抓取）。

    - force=True 时直接抓取（放入线程池，避免阻塞事件循环）。
    - 冷缓存且本地文件有内容时快速返回，不做阻塞式全量 RSS 抓取。
    - 抓取放入 asyncio.to_thread，避免 15s 全量抓取阻塞事件循环拖慢同进程其它请求。
    """
    import asyncio
    from app.services.cache_layer import get_cache, set_cache

    if force:
        return await asyncio.to_thread(fetch_radar)

    hit = await get_cache("vibe:news_radar")
    if hit is not None:
        return hit

    local_data = load_cache()
    if _has_content(local_data):
        return local_data

    data = await asyncio.to_thread(fetch_radar)
    if _has_content(data):
        await set_cache("vibe:news_radar", data, category="news")
    else:
        # 抓取为空（网络故障等）时兜底返回既有本地缓存，避免前端看到空数据
        fallback = load_cache()
        if _has_content(fallback):
            return fallback
    return data
