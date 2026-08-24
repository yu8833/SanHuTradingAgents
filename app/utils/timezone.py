from __future__ import annotations

from datetime import datetime
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

