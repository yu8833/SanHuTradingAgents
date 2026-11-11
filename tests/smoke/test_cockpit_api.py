"""冒烟测试：交易驾驶舱接口最小正向路径。

断言 8 接口的 {success, data, message} 契约与关键字段；
POST 做一次 标记买入→了结 往返（在开发库留下一条 closed 记录，可接受）。
POST /api/cockpit/pool/rescan 为全市场重扫（分钟级），不在冒烟范围，由手动触发验证。
"""
import pytest

pytestmark = pytest.mark.smoke

GET_ENDPOINTS = [
    ("/api/cockpit/gate", ["gate", "label", "position_hint", "emotion_phase", "as_of_portrait", "as_of_emotion"]),
    ("/api/cockpit/mainline", ["mainlines", "periods", "source"]),
    ("/api/cockpit/pool", ["items", "total", "params", "params_version", "params_note"]),
    ("/api/cockpit/signals", ["triggered", "near", "watching_count", "trading_session"]),
    ("/api/cockpit/positions", ["items", "evaluated_at", "trade_date", "is_intraday"]),
]


async def _get(http_client, path):
    try:
        return await http_client.get(path)
    except Exception as exc:
        pytest.skip(f"本地服务未启动，跳过：{exc}")


class TestCockpitGetContract:
    @pytest.mark.parametrize("path,keys", GET_ENDPOINTS)
    async def test_contract_and_key_fields(self, http_client, auth_token, path, keys):
        if not auth_token:
            pytest.skip("无登录态，跳过")
        resp = await _get(http_client, path)
        assert resp.status_code == 200, f"{path} 返回 {resp.status_code}: {resp.text[:300]}"
        body = resp.json()
        assert body.get("success") is True, f"{path} success!=True: {body}"
        data = body.get("data") or {}
        for k in keys:
            assert k in data, f"{path} 缺少字段 {k}"


class TestCockpitGateSemantics:
    async def test_gate_enum_and_params_note(self, http_client, auth_token):
        if not auth_token:
            pytest.skip("无登录态，跳过")
        resp = await _get(http_client, "/api/cockpit/gate")
        data = resp.json()["data"]
        assert data["gate"] in ("green", "yellow", "red")
        assert data["label"] in ("可进攻", "轻仓试错", "空仓等待")

        resp = await _get(http_client, "/api/cockpit/pool")
        data = resp.json()["data"]
        assert data["params_note"] == "经验参数 · 待回测校准"


class TestCockpitPositionRoundtrip:
    async def test_create_then_close(self, http_client, auth_token):
        if not auth_token:
            pytest.skip("无登录态，跳过")
        try:
            create = await http_client.post(
                "/api/cockpit/positions", json={"code": "600000", "buy_price": 10.0}
            )
        except Exception as exc:
            pytest.skip(f"本地服务未启动，跳过：{exc}")
        assert create.status_code == 200, create.text[:300]
        body = create.json()
        assert body.get("success") is True, body
        pos_id = (body.get("data") or {}).get("id")
        assert pos_id

        close = await http_client.post(
            f"/api/cockpit/positions/{pos_id}/close", json={"sell_price": 10.5}
        )
        assert close.status_code == 200, close.text[:300]
        assert close.json().get("success") is True

        # 默认列表不含已了结
        listed = await _get(http_client, "/api/cockpit/positions")
        items = listed.json()["data"]["items"]
        assert all(i["id"] != pos_id for i in items)

    async def test_close_invalid_id_fails_gracefully(self, http_client, auth_token):
        if not auth_token:
            pytest.skip("无登录态，跳过")
        resp = await http_client.post(
            "/api/cockpit/positions/not-an-object-id/close", json={"sell_price": 10.5}
        )
        assert resp.status_code == 200
        assert resp.json().get("success") is False

    async def test_create_rejects_nonpositive_price(self, http_client, auth_token):
        if not auth_token:
            pytest.skip("无登录态，跳过")
        resp = await http_client.post("/api/cockpit/positions", json={"code": "600000", "buy_price": 0})
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            assert resp.json().get("success") is False
