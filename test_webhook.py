"""WebhookPush 插件单元测试"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from plugins.WebhookPush.main import WebhookPush

TOKEN_SECURED = ""
TOKEN_OPEN = ""
API_KEY = ""


class FakeRequest:
    def __init__(
        self,
        body: dict | None = None,
        *,
        method: str = "POST",
        headers: dict | None = None,
        query: dict | None = None,
    ):
        self._body = body or {}
        self.method = method
        self.headers = headers or {}
        self.query_params = query or {}

    async def json(self):
        return self._body


def post_payload(content: str, from_source: str = "") -> dict:
    data = {"content": content}
    if from_source:
        data["from"] = from_source
    return data


async def run_tests() -> None:
    plugin = WebhookPush()
    assert TOKEN_SECURED in plugin.token_map
    assert plugin.token_map[TOKEN_SECURED]["api_key"] == API_KEY
    assert plugin.token_map[TOKEN_OPEN]["api_key"] == ""

    resp = await plugin.handle_webhook("bad-token", FakeRequest(post_payload("hi")))
    assert json.loads(resp.body)["code"] == 19001

    resp = await plugin.handle_webhook(
        TOKEN_SECURED,
        FakeRequest(post_payload("hi")),
    )
    assert json.loads(resp.body)["code"] == 19009

    resp = await plugin.handle_webhook(
        TOKEN_SECURED,
        FakeRequest(
            post_payload("hi"),
            headers={"api_key": "wrong-key"},
        ),
    )
    assert json.loads(resp.body)["code"] == 19010

    resp = await plugin.handle_webhook(
        TOKEN_OPEN,
        FakeRequest(post_payload("  ")),
    )
    assert json.loads(resp.body)["code"] == 19007

    with patch.object(WebhookPush, "_resolve_client", return_value=None):
        resp = await plugin.handle_webhook(
            TOKEN_OPEN,
            FakeRequest(post_payload("hello")),
        )
    assert json.loads(resp.body)["code"] == 19002

    plugin._last_request_at.clear()
    mock_client = MagicMock()
    mock_client.send_text_message = AsyncMock(return_value=(1, 2, 3))
    with patch.object(WebhookPush, "_resolve_client", return_value=mock_client):
        plugin._last_request_at[TOKEN_OPEN] = time.monotonic()
        resp = await plugin.handle_webhook(
            TOKEN_OPEN,
            FakeRequest(post_payload("hello")),
        )
    assert json.loads(resp.body)["code"] == 19004

    plugin._last_request_at.clear()
    with patch.object(WebhookPush, "_resolve_client", return_value=mock_client):
        resp = await plugin.handle_webhook(
            TOKEN_OPEN,
            FakeRequest(post_payload("hello", "CI")),
        )
    assert json.loads(resp.body)["code"] == 0
    mock_client.send_text_message.assert_awaited_with(
        plugin.token_map[TOKEN_OPEN]["group_wxid"],
        "[CI] hello",
        "",
    )

    plugin._last_request_at.clear()
    with patch.object(WebhookPush, "_resolve_client", return_value=mock_client):
        resp = await plugin.handle_webhook(
            TOKEN_SECURED,
            FakeRequest(
                post_payload("secure msg", "Bot"),
                headers={"api_key": API_KEY},
            ),
        )
    assert json.loads(resp.body)["code"] == 0

    plugin._last_request_at.clear()
    with patch.object(WebhookPush, "_resolve_client", return_value=mock_client):
        resp = await plugin.handle_webhook(
            TOKEN_SECURED,
            FakeRequest(
                {
                    "api_key": API_KEY,
                    "content": "body key msg",
                    "from": "CUSTOM_HTTP",
                }
            ),
        )
    assert json.loads(resp.body)["code"] == 0

    plugin._last_request_at.clear()
    with patch.object(WebhookPush, "_resolve_client", return_value=mock_client):
        resp = await plugin.handle_webhook(
            TOKEN_SECURED,
            FakeRequest(
                {
                    "api": API_KEY,
                    "content": "body api alias msg",
                    "from": "CUSTOM_HTTP",
                }
            ),
        )
    assert json.loads(resp.body)["code"] == 0

    resp = await plugin.handle_webhook(
        TOKEN_OPEN,
        FakeRequest(method="GET", query={"content": "disk full", "from": "Monitor"}),
    )
    assert json.loads(resp.body)["code"] == 19002

    plugin.enable = False
    resp = await plugin.handle_webhook(TOKEN_OPEN, FakeRequest(post_payload("hello")))
    assert json.loads(resp.body)["code"] == 19005

    print("All WebhookPush handler tests passed.")


def run_http_tests() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import admin.server as server_module
    import plugins.WebhookPush.main as wp_main

    app = FastAPI()
    original_app = server_module.app
    server_module.app = app
    wp_main._ROUTES_REGISTERED = False

    try:
        WebhookPush()._register_routes()
        client = TestClient(app)

        r = client.post(
            f"/api/webhook/{TOKEN_OPEN}",
            json=post_payload("hi"),
        )
        assert r.json()["code"] == 19002

        mock_client = MagicMock()
        mock_client.send_text_message = AsyncMock(return_value=(1, 2, 3))
        with patch.object(WebhookPush, "_resolve_client", return_value=mock_client):
            r = client.post(
                f"/api/webhook/{TOKEN_OPEN}",
                json=post_payload("hi", "Test"),
            )
            assert r.json()["code"] == 0

            r2 = client.get(
                f"/api/webhook/{TOKEN_OPEN}",
                params={"content": "get msg", "from": "Cron"},
            )
            assert r2.json()["code"] == 19004

        print("All WebhookPush HTTP tests passed.")
    finally:
        server_module.app = original_app
        wp_main._ROUTES_REGISTERED = False


if __name__ == "__main__":
    asyncio.run(run_tests())
    run_http_tests()
