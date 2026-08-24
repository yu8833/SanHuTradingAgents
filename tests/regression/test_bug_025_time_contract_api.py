"""
Bug-025 防回归测试：时间契约统一（穿越测试）

背景：全系统曾多次出现时间相关 bug（速览"过期一天"、历史K线 unknown、K线缓存失效、
T+1 判定错 8 小时等），根因是存储形态混存 + naive 二义性 + 字符串/对象混存。

统一契约（见 docs/design/time-contract-plan.md）：
  1. 写时刻：一律 `now_tz()`（aware +08:00），禁 `now_tz().replace(tzinfo=None)` 存 naive。
  2. 数据库读出：naive = UTC（tz_aware=True 后读回即 aware UTC）。
  3. 读出→显示：`to_display_iso()`（恒定 +08:00）。
  4. 读出→计算：`to_config_tz()`（naive 按 UTC 解释再转配置时区）。
  5. API 边界：所有 datetime 出参必须带 +08:00，无时区/非 +08:00 字符串永不过线。
  6. 时区源唯一：`get_tz()`，禁 `ZoneInfo(settings.TIMEZONE)` 直引分叉。
  7. 死代码 `ensure_timezone`（naive=京时，语义相反）已删除。

本测试从三条自动化维度锁定契约，防止回归：
  A. 工具语义（to_display_iso / to_config_tz / now_tz）确定性断言
  B. 源码级守卫：写反模式（naive 写、ISO 字符串裸序列化、时区源分叉、ensure_timezone）不得回归
  C. 代表性 API 出参恒带 +08:00
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
APP_ROOT = PROJECT_ROOT / "app"


# ==================================================================
# A. 工具语义确定性断言
# ==================================================================

def test_time_contract_now_tz_is_aware_beijing():
    """now_tz() 必须返回带 +08:00 时区的 aware datetime。"""
    from app.utils.timezone import now_tz
    dt = now_tz()
    assert dt.tzinfo is not None, "now_tz() 必须返回 aware datetime"
    assert dt.utcoffset().total_seconds() == 8 * 3600, (
        f"now_tz() 偏移必须是 +08:00，实际 {dt.utcoffset()}"
    )
    # isoformat 必须显式携带 +08:00
    assert dt.isoformat().endswith("+08:00"), f"now_tz().isoformat() 应带 +08:00，实际 {dt.isoformat()}"


def test_time_contract_to_display_iso_always_beijing():
    """to_display_iso() 无论输入 naive(UTC)/aware(UTC)/aware(北京)，输出恒定 +08:00。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.utils.timezone import to_display_iso

    naive_utc = datetime(2026, 8, 20, 12, 0, 0)                     # naive，按 UTC 解释
    aware_utc = naive_utc.replace(tzinfo=ZoneInfo("UTC"))           # aware UTC
    aware_bj = aware_utc.astimezone(ZoneInfo("Asia/Shanghai"))      # aware 北京

    for val in (naive_utc, aware_utc, aware_bj):
        out = to_display_iso(val)
        assert out is not None and out.endswith("+08:00"), (
            f"to_display_iso({val}) 必须输出 +08:00，实际 {out}"
        )
    # 同一瞬时三种输入，须得到完全相同的字符串
    assert to_display_iso(naive_utc) == to_display_iso(aware_utc) == to_display_iso(aware_bj)

    # None 输入 → None
    assert to_display_iso(None) is None


def test_time_contract_to_config_tz_naive_assumed_utc():
    """to_config_tz() 对 naive 输入按 UTC 解释，再转配置时区(+08:00)。"""
    from datetime import datetime

    from app.utils.timezone import to_config_tz

    naive = datetime(2026, 8, 20, 12, 0, 0)
    out = to_config_tz(naive)
    assert out is not None and out.tzinfo is not None
    assert out.utcoffset().total_seconds() == 8 * 3600  # +08:00
    # naive 12:00 (UTC) = 北京 20:00
    assert out.hour == 20, f"naive UTC 12:00 应转成北京 20:00，实际 {out.hour}"

    assert to_config_tz(None) is None


# ==================================================================
# B. 源码级守卫：反模式不得回归
# ==================================================================

def _walk_py():
    for p in APP_ROOT.rglob("*.py"):
        yield p


def test_time_contract_no_ensure_timezone():
    """死代码 ensure_timezone（naive=京时，语义相反）不得存在于 app/。"""
    for p in _walk_py():
        text = p.read_text(encoding="utf-8")
        assert "def ensure_timezone" not in text, (
            f"{p.relative_to(PROJECT_ROOT)} 仍存在 ensure_timezone 定义（时间契约已将其删除）"
        )


def test_time_contract_no_naive_write_antipattern():
    """写反模式：`now_tz().replace(tzinfo=None)` 存 naive 会造成 +8h 偏移，禁止出现。"""
    pattern_naive = "now_tz().replace(tzinfo=None)"
    pattern_naive2 = "now_tz().replace(tzinfo="
    hits = []
    for p in _walk_py():
        text = p.read_text(encoding="utf-8")
        if pattern_naive in text or pattern_naive2 in text:
            hits.append(str(p.relative_to(PROJECT_ROOT)))
    assert not hits, f"存在 naive 写反模式（strip tzinfo）：{hits}"


def test_time_contract_no_zoneinfo_global_diverge():
    """时区源唯一：不得 `ZoneInfo(settings.TIMEZONE)` 直引分叉（应统一 get_tz()）。"""
    hits = []
    for p in _walk_py():
        text = p.read_text(encoding="utf-8")
        if "ZoneInfo(settings.TIMEZONE)" in text:
            hits.append(str(p.relative_to(PROJECT_ROOT)))
    assert not hits, f"存在时区源直引分叉 ZoneInfo(settings.TIMEZONE)：{hits}"


def test_time_contract_no_scheduler_tz_setsettings_divergence():
    """
    调度/交易时间若以 settings.TIMEZONE 绑定 APScheduler cron，会与 get_tz()
   （DB 可动态覆盖）分叉，导致任务触发时刻在运行期改时区后错位。
   禁 `tz = settings.TIMEZONE` 或 `timezone=settings.TIMEZONE` 这种"直取静态值"写法。
   注：settings.TIMEZONE 仅允许作为 timezone.py 的默认回退及日志文案出现，禁用于调度绑定/时刻计算。
    """
    banned_assign = ["tz = settings.TIMEZONE", "timezone=settings.TIMEZONE"]
    hits = []
    for p in _walk_py():
        if p.name == "timezone.py":
            continue
        text = p.read_text(encoding="utf-8")
        for pat in banned_assign:
            if pat in text:
                hits.append((str(p.relative_to(PROJECT_ROOT)), pat))
    assert not hits, f"存在以 settings.TIMEZONE 绑定调度/时刻的分叉：{hits}"


def test_time_contract_to_config_tz_accepts_iso_string():
    """写入契约切换前的存量 ISO 字符串，to_config_tz 必须可解析（缺失时区按 UTC 解释）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.utils.timezone import to_config_tz

    naive_str = "2026-08-20T12:00:00"                      # 存量字符串，无偏移
    out = to_config_tz(naive_str)
    assert out is not None and out.tzinfo is not None
    assert out.utcoffset().total_seconds() == 8 * 3600
    assert out.hour == 20, f"naive ISO 12:00 按 UTC 应转北京 20:00，实际 {out.hour}"

    aware_bj_str = "2026-08-20T20:00:00+08:00"              # 存量字符串，带 +08:00
    out2 = to_config_tz(aware_bj_str)
    assert out2 is not None and out2.hour == 20

    assert to_config_tz(None) is None


def test_time_contract_to_display_iso_accepts_iso_string():
    """存量 ISO 字符串经 to_display_iso 归一为 +08:00，兼容 tz_aware 混合读取。"""
    from app.utils.timezone import to_display_iso

    naive_str = "2026-08-20T12:00:00"
    assert to_display_iso(naive_str) == "2026-08-20T20:00:00+08:00", (
        f"naive ISO 字符串按 UTC 解释后应归一为 +08:00，实际 {to_display_iso(naive_str)}"
    )
    aware_bj_str = "2026-08-20T20:00:00+08:00"
    assert to_display_iso(aware_bj_str) == "2026-08-20T20:00:00+08:00"
    assert to_display_iso(None) is None


def test_time_contract_multi_source_sync_status_no_iso_write():
    """
    写入存储契约（批次5）：sync_status 的 started_at/finished_at 已迁移为 BSON datetime。
    multi_source_basics_sync_service 不得再以 ISO 字符串写入时间字段（禁 .isoformat()），
    否则会与已迁移的 datetime + tz_aware 读回混存，重蹈字符串/对象混存覆辙。
    """
    target = APP_ROOT / "services" / "multi_source_basics_sync_service.py"
    text = target.read_text(encoding="utf-8")
    assert "isoformat" not in text, (
        "multi_source_basics_sync_service 写入侧已切换为 now_tz()(datetime)，禁止出现 .isoformat() 写时间字段"
    )


def test_time_contract_scheduler_output_uses_display_iso():
    """
    代表性 API 出参：调度执行历史序列化必须走 to_display_iso（而非裸 isoformat），
    保证 tz_aware 下读回 aware UTC 也归一为 +08:00。
    """
    from app.services import scheduler_service
    import inspect

    scheduler_src = Path(inspect.getfile(scheduler_service)).read_text(encoding="utf-8")
    assert "to_display_iso" in scheduler_src
    # 读取执行记录的时间字段（scheduled_time/timestamp/updated_at）不应再用裸 .isoformat()
    assert "doc[time_field] = to_display_iso(doc[time_field])" in scheduler_src, (
        "执行历史时间字段必须统一走 to_display_iso，禁止裸 .isoformat()"
    )
    assert "doc[time_field] = dt.isoformat()" not in scheduler_src


# ==================================================================
# C. 代表性 API 出参恒带 +08:00（借助 scheduler 序列化函数 / 工具串联）
# ==================================================================

def test_time_contract_execution_timestamp_pipeline_end_to_end():
    """
    模拟 tz_aware 读回路径：DB 存 BSON datetime(UTC)，读回 aware UTC，
    经 to_display_iso 归一后得到 +08:00，端到端无无偏移字符串漏出。
    """
    from datetime import datetime, timezone

    from app.utils.timezone import to_display_iso

    db_stored_utc = datetime(2026, 8, 20, 4, 30, 0, tzinfo=timezone.utc)  # 读回（tz_aware）
    rendered = to_display_iso(db_stored_utc)
    assert rendered == "2026-08-20T12:30:00+08:00", f"端到端渲染错误：{rendered}"
    # 契约硬性要求：无时区偏字符串不得过线
    assert "+08:00" in rendered