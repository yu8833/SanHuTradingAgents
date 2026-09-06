"""置信度统计校准：把「决策→实际收益→alpha 反思」闭环升级为批量命中率统计。

背景：
- `final_confidence` 是 LLM 主观数字，虽有 memory log 的决策复盘闭环，
  但没有「评级 vs 实际命中率」的批量统计，无法验证 80 与 60 的差别。
- 本模块从 memory log 加载已复盘（resolved）条目，按评级分桶统计
  方向性命中率（Wilson 95% 区间 + Brier），并按置信度分桶生成校准曲线；
  统计结果可注入风控/组合经理 prompt 作经验基线，或经 API 暴露给前端。

口径：
- 命中定义：买入/增持 → raw>0；减持/卖出 → raw<0；持有仅报告均值，不参与命中率。
- confidence 校准曲线依赖 analysis_reports 的置信度（key=(stock_symbol, analysis_date)），
  由调用方（router）反查后传入，本模块保持纯函数可测。
"""

from __future__ import annotations

import logging
from pathlib import Path

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

# 方向性评级（命中率只对方向性样本统计；Hold 仅报告均值）
_BULLISH = frozenset({"Buy", "Overweight"})
_BEARISH = frozenset({"Underweight", "Sell"})

# 校准曲线置信度分桶（claimed 区间）
_CALIBRATION_BUCKETS: list[tuple[str, object]] = [
    ("<0.5", lambda c: c < 0.5),
    ("0.5-0.6", lambda c: 0.5 <= c < 0.6),
    ("0.6-0.7", lambda c: 0.6 <= c < 0.7),
    ("0.7-0.8", lambda c: 0.7 <= c < 0.8),
    (">=0.8", lambda c: c >= 0.8),
]

# 注入命中率文案的最小样本量（低于该值避免小样本误导）
_MIN_SAMPLE = 10


# ---------------------------------------------------------------------------
# 加载与解析
# ---------------------------------------------------------------------------


def _memory_log_path() -> Path | None:
    try:
        p = (get_config() or {}).get("memory_log_path")
        return Path(p).expanduser() if p else None
    except Exception:
        return None


def _parse_pct(value) -> float | None:
    """把 tag 中的收益字符串（如 '+5.2%' / '-1.0%' / 'n/a'）解析为小数。

    结果四舍五入到 4 位小数，避免 `float(x)/100` 的二进制浮点尾巴（如 0.052000000000000005）。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("n/a", "nan", "none", "pending"):
        return None
    try:
        return round(float(s.rstrip("%")) / 100.0, 4)
    except ValueError:
        return None


def load_entries() -> list[dict]:
    """加载 memory log 已复盘条目（pending=False），并解析 raw/alpha 为小数。

    字段：date / ticker / rating / raw / alpha / holding / decision / reflection /
          raw_f / alpha_f（数值化）。
    """
    try:
        from tradingagents.agents.utils.memory import TradingMemoryLog

        entries = TradingMemoryLog(get_config()).load_entries()
    except Exception as e:
        logger.warning("加载 memory log 失败: %s", e)
        return []

    resolved = [e for e in entries if not e.get("pending")]
    for e in resolved:
        e["raw_f"] = _parse_pct(e.get("raw"))
        e["alpha_f"] = _parse_pct(e.get("alpha"))
    return resolved


# ---------------------------------------------------------------------------
# 命中率统计
# ---------------------------------------------------------------------------


def _wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval 95% 置信区间（小样本更稳健）。"""
    if n <= 0:
        return 0.0, 0.0
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _is_hit(e: dict, rating: str, use_alpha: bool = False) -> bool | None:
    """方向性命中判断；Hold/未知评级返回 None（不参与命中率）。

    rating="overall" 时按条目自身评级判断方向。
    """
    if rating == "overall":
        rating = e.get("rating", "")
    field = "alpha_f" if use_alpha else "raw_f"
    val = e.get(field)
    if val is None:
        return None
    if rating in _BULLISH:
        return val > 0
    if rating in _BEARISH:
        return val < 0
    return None


def _bucket_stats(items: list[dict], rating: str) -> dict:
    """单桶统计：{n, abs_hit_rate, alpha_hit_rate, avg_raw, avg_alpha, wilson_ci, brier}。"""
    n = len(items)
    empty = {
        "n": 0, "abs_hit_rate": None, "alpha_hit_rate": None,
        "avg_raw": None, "avg_alpha": None,
        "wilson_ci_lo": None, "wilson_ci_hi": None, "brier": None,
    }
    if n == 0:
        return empty

    raw_vals = [e["raw_f"] for e in items if e.get("raw_f") is not None]
    alpha_vals = [e["alpha_f"] for e in items if e.get("alpha_f") is not None]
    avg_raw = sum(raw_vals) / len(raw_vals) if raw_vals else None
    avg_alpha = sum(alpha_vals) / len(alpha_vals) if alpha_vals else None

    # Hold / 无方向性语义的桶：仅报告均值
    if rating != "overall" and rating not in _BULLISH and rating not in _BEARISH:
        return {
            "n": n, "abs_hit_rate": None, "alpha_hit_rate": None,
            "avg_raw": round(avg_raw, 4) if avg_raw is not None else None,
            "avg_alpha": round(avg_alpha, 4) if avg_alpha is not None else None,
            "wilson_ci_lo": None, "wilson_ci_hi": None, "brier": None,
        }

    abs_hits = sum(1 for e in items if _is_hit(e, rating) is True)
    alpha_hits = sum(1 for e in items if _is_hit(e, rating, use_alpha=True) is True)
    abs_hit_rate = abs_hits / n
    alpha_hit_rate = alpha_hits / n
    lo, hi = _wilson_ci(abs_hit_rate, n)
    return {
        "n": n,
        "abs_hit_rate": round(abs_hit_rate, 4),
        "alpha_hit_rate": round(alpha_hit_rate, 4),
        "avg_raw": round(avg_raw, 4) if avg_raw is not None else None,
        "avg_alpha": round(avg_alpha, 4) if avg_alpha is not None else None,
        "wilson_ci_lo": round(lo, 4),
        "wilson_ci_hi": round(hi, 4),
        "brier": round(1.0 - abs_hit_rate, 4),  # 二分类方向预测下 Brier = miss rate
    }


def compute_rating_stats(entries: list[dict]) -> dict:
    """按评级分桶统计命中率，返回 {"per_rating": {...}, "overall": {...}}。

    分桶：Buy / Overweight / Hold / Underweight / Sell（RATINGS_5_TIER）；
    overall 为全部方向性样本（Buy+Overweight+Underweight+Sell）合计。
    """
    buckets: dict[str, list] = {"Buy": [], "Overweight": [], "Hold": [],
                                "Underweight": [], "Sell": []}
    for e in entries:
        rating = e.get("rating", "")
        if rating in buckets:
            buckets[rating].append(e)

    per_rating = {rating: _bucket_stats(items, rating)
                  for rating, items in buckets.items()}

    directional = [e for r, items in buckets.items() if r in _BULLISH | _BEARISH
                   for e in items]
    overall = _bucket_stats(directional, "overall")
    return {"per_rating": per_rating, "overall": overall}


def compute_calibration_curve(
    memory_entries: list[dict],
    db_confidence_map: dict[tuple, float],
) -> list[dict]:
    """按置信度分桶：每桶 {bucket, n, claimed, empirical}。

    claimed = 桶内置信度均值（0-1）；empirical = 桶内方向性样本的命中率。
    db_confidence_map: {(stock_symbol, analysis_date): confidence_score}，
    由调用方从 analysis_reports 反查；无匹配的条目不进入曲线。
    """
    acc = {name: {"claimed_sum": 0.0, "hits": 0, "n": 0, "dir_n": 0}
           for name, _ in _CALIBRATION_BUCKETS}
    for e in memory_entries:
        conf = db_confidence_map.get((e.get("ticker"), e.get("date")))
        if conf is None:
            continue
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= conf <= 1.0):
            continue
        for name, pred in _CALIBRATION_BUCKETS:
            if pred(conf):
                acc[name]["claimed_sum"] += conf
                acc[name]["n"] += 1
                hit = _is_hit(e, "overall")
                if hit is not None:
                    acc[name]["dir_n"] += 1
                    if hit:
                        acc[name]["hits"] += 1
                break

    curve = []
    for name, _ in _CALIBRATION_BUCKETS:
        b = acc[name]
        claimed = b["claimed_sum"] / b["n"] if b["n"] else None
        empirical = b["hits"] / b["dir_n"] if b["dir_n"] else None
        curve.append({
            "bucket": name,
            "n": b["n"],
            "claimed": round(claimed, 4) if claimed is not None else None,
            "empirical": round(empirical, 4) if empirical is not None else None,
        })
    return curve


def calibration_injection_text(stats: dict) -> str:
    """生成注入风控/组合经理 prompt 的经验命中率文案。

    仅当方向性样本合计 >= _MIN_SAMPLE 时返回；否则空串（避免小样本误导）。
    """
    overall = (stats or {}).get("overall") or {}
    n = overall.get("n") or 0
    if n < _MIN_SAMPLE:
        return ""

    def fmt_rate(v) -> str:
        return f"{v * 100:.0f}%" if v is not None else "n/a"

    lines = ["📊 历史命中率统计（来自 memory log 决策复盘）："]
    per_rating = (stats or {}).get("per_rating") or {}
    for key, cn in (("Buy", "买入"), ("Overweight", "增持"),
                    ("Underweight", "减持"), ("Sell", "卖出")):
        b = per_rating.get(key) or {}
        if (b.get("n") or 0) >= _MIN_SAMPLE:
            lines.append(
                f"- {cn}评级命中率 {fmt_rate(b.get('abs_hit_rate'))}"
                f"（N={b['n']}，alpha 命中 {fmt_rate(b.get('alpha_hit_rate'))}）"
            )
    lines.append(
        f"- 方向性样本合计命中率 {fmt_rate(overall.get('abs_hit_rate'))}"
        f"（N={n}，alpha 命中 {fmt_rate(overall.get('alpha_hit_rate'))}）"
    )
    lines.append(
        "请结合经验命中率校准置信度，避免过度自信；"
        "命中率明显偏低的方向应相应降低仓位。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 缓存（memory log mtime 失效）
# ---------------------------------------------------------------------------

_cached_stats: dict | None = None
_cached_mtime: float = -1.0


def get_rating_stats() -> dict:
    """带 memory log mtime 缓存的命中率统计（文件小，重算开销 <10ms）。"""
    global _cached_stats, _cached_mtime
    path = _memory_log_path()
    mtime = path.stat().st_mtime if path and path.exists() else 0.0
    if _cached_stats is not None and mtime == _cached_mtime:
        return _cached_stats
    stats = compute_rating_stats(load_entries())
    _cached_stats = stats
    _cached_mtime = mtime
    return stats


def invalidate_calibration_cache() -> None:
    """memory log 批量更新成功后调用，强制下次重算。"""
    global _cached_stats, _cached_mtime
    _cached_stats = None
    _cached_mtime = -1.0
