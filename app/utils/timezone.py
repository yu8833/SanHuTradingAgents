from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


def get_tz_name() -> str:
    """Return configured timezone name, preferring DB system_settings.app_timezone if cached.
    Fallback order: DB (cached) > env (settings.TIMEZONE) > Asia/Shanghai.
    This function is sync and must not await; it relies on provider cache populated elsewhere.
    """
    try:
        # Lazy import to avoid circular imports
        from app.services.config_provider import provider as cfgprov  # type: ignore
        cached = getattr(cfgprov, "_cache_settings", None)
        if isinstance(cached, dict):
            tz = cached.get("app_timezone") or cached.get("APP_TIMEZONE")
            if isinstance(tz, str) and tz.strip():
                return tz.strip()
    except Exception:
        pass
    return settings.TIMEZONE or "Asia/Shanghai"


def get_tz() -> ZoneInfo:
    return ZoneInfo(get_tz_name())


def now_tz() -> datetime:
    """Current time in configured timezone (tz-aware)."""
    return datetime.now(get_tz())


def parse_beijing_naive(dt_str: str) -> datetime | None:
    """解析「北京时间」的字符串（无时区/naive）为 aware UTC datetime，供 Mongo 统一按 UTC 存储。

    处理规则（与 MongoDB「统一 UTC 存储」约定对齐，供写入端使用）：
      - 常见北京墙钟格式（%Y-%m-%d %H:%M:%S / %Y-%m-%d %H:%M / %Y-%m-%d / %Y%m%d%H%M%S）
        解析出的 naive 按「北京时间」解释，转为 UTC（-8h，aware）；
      - 带 Z 后缀（ISO UTC）或已带时区的输入：按 UTC/自带偏移归一，不重复 -8h；
      - 解析失败返回 None（调用方自行降级，避免把脏值当时间入库）。
    返回值为 aware UTC，motor 写入即正确；读回 tz_aware=True 为 UTC aware，
    展示侧用 to_config_tz / to_display_iso 转北京时间即可。
    """
    if not dt_str:
        return None
    s = str(dt_str).strip()
    if not s:
        return None
    # 已带时区偏移（如 2026-09-24T07:58:58+00:00）或 Z 后缀（UTC）：按自带语义归一
    if s.endswith("Z") or s.endswith("z"):
        try:
            body = s[:-1].rstrip("Zz")
            return datetime.fromisoformat(body + "+00:00").astimezone(timezone.utc)
        except ValueError:
            pass
    if "+" in s or "-" in s[10:]:
        # 已带显式偏移（ISO）的输入：按字符串自带偏移归一，不做 -8h
        try:
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            naive = datetime.strptime(s, fmt)
            # 北京墙钟 naive → UTC aware（-8h）
            return naive.replace(tzinfo=get_tz()).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def to_config_tz(dt: datetime | str | None) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        # 数据库读回可能是历史 ISO 字符串（写入契约切换前的存量数据）。
        # 缺失时区的字符串按 UTC 解释；带偏移的按字符串自带的偏移归一。
        parsed = datetime.fromisoformat(dt)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        dt = parsed
    if dt.tzinfo is None:
        # Treat naive as UTC by default, then convert to configured tz
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(get_tz())
    return dt.astimezone(get_tz())


def to_display_iso(dt: datetime | str | None) -> str | None:
    """将数据库读出的 datetime 统一转为北京时间（+08:00）的 ISO 字符串。

    MongoDB 内部统一以 UTC 存储 datetime，且当前 motor 客户端未开启 tz_aware，
    读回的值是"无时区"的 UTC 墙钟时间。因此：
      - naive datetime：按 UTC 解释，再转换为北京时间
      - 已带时区的 datetime：直接转换为北京时间
      - ISO 字符串（写入契约切换前的存量数据）：缺失时区按 UTC 解释，带偏移按偏移归一
    这样所有输出都给前端带 +08:00 时区标识，避免 8 小时偏差。
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        parsed = datetime.fromisoformat(dt)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(get_tz()).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(get_tz()).isoformat()

