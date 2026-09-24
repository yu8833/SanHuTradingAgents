"""
防回归测试：新闻 publish_time 时区处理（写入端 UTC 统一 + 数据健康读取转换）

背景（bug）：新闻源（东财/akshare/tushare）返回的发布时间为「北京时间墙钟」，
但写入端曾用 strptime 解析出 naive datetime 直接入库，被 motor 当 UTC 存储，
导致库里 publish_time 比真实晚 8 小时（07:58 北京存成 07:58 UTC = 15:58 北京），
数据健康接口读回转北京后显示成未来时间。

修复（现行）：
    - 写入端：parse_beijing_naive() 把北京墙钟字符串解析为 aware UTC（-8h），
      news_data_sync_service / news_data_service / vibe_research 三处统一使用；
    - 读取端：screening 数据健康对 publish_time 继续走 to_config_tz（UTC→北京），
      与 basics/financial 等其它数据项口径一致。

测试要点：
    - timezone.parse_beijing_naive 必须把北京字符串转为 UTC（-8h）aware；
    - 三个写入入口必须引用 parse_beijing_naive（不得再用裸 strptime 存 naive）；
    - screening 数据健康新闻项必须保留 to_config_tz（不得删掉导致读回不转换）。
"""
import os

import pytest

from app.utils.timezone import parse_beijing_naive

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.mark.regression
def test_parse_beijing_naive_converts_to_utc():
    """北京墙钟字符串应解析为 aware UTC（-8h）"""
    from datetime import timezone

    dt = parse_beijing_naive("2026-09-23 07:58:58")
    assert dt is not None
    assert dt.tzinfo is not None, "必须返回 aware datetime"
    assert dt.utcoffset() == timezone.utc.utcoffset(None), "应为 UTC aware"
    # 07:58 北京 = 23:58 UTC（前一日）
    assert dt.hour == 23, f"07:58 北京应转为 23 时 UTC，实际 {dt.hour}"
    assert dt.day == 22, f"07:58 北京应转为前一日 22 日，实际 {dt.day}"
    # 转回北京应还原
    from zoneinfo import ZoneInfo
    assert dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M") == "07:58"


@pytest.mark.regression
def test_parse_beijing_naive_z_suffix_keeps_utc():
    """Z 后缀（ISO UTC）不应重复 -8h"""
    dt = parse_beijing_naive("2026-09-23T07:58:58Z")
    assert dt is not None
    assert dt.hour == 7, f"Z 后缀是 UTC，不应再 -8h，实际 {dt}"
    from zoneinfo import ZoneInfo
    assert dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M") == "15:58"


@pytest.mark.regression
def test_write_paths_use_parse_beijing_naive():
    """三个新闻写入入口必须使用 parse_beijing_naive（统一 UTC 写入），不得裸 strptime 存 naive"""
    targets = [
        ("app/worker/news_data_sync_service.py", "parse_beijing_naive"),
        ("app/services/news_data_service.py", "parse_beijing_naive"),
        ("app/routers/vibe_research.py", "parse_beijing_naive"),
    ]
    for rel, marker in targets:
        path = os.path.join(_PROJECT_ROOT, rel)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert marker in content, f"{rel} 必须使用 {marker} 统一写入 publish_time"


@pytest.mark.regression
def test_screening_news_keeps_tz_convert():
    """数据健康新闻项必须保留 to_config_tz（UTC→北京），不得删掉"""
    path = os.path.join(_PROJECT_ROOT, "app", "routers", "screening.py")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # 新闻分支区段（publish_time 处理处）应包含 to_config_tz
    idx = content.find("news_updated_at = None")
    assert idx != -1
    section = content[idx:idx + 1200]
    assert "to_config_tz" in section, \
        "数据健康新闻项必须继续用 to_config_tz 转北京时间（写入端已统一 UTC）"
