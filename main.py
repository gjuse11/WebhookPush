"""
@input: config.toml 中的 webhook token、api_key 与群 ID、外部 HTTP 请求
@output: 向指定群推送纯文本消息（通用 webhook 格式）
@position: 插件层 inbound webhook，为 CI/监控等外部系统提供群消息推送入口
"""

from __future__ import annotations

import inspect
import time
import tomllib
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger

from utils.plugin_base import PluginBase

_ROUTES_REGISTERED = False


class WebhookPush(PluginBase):
    description = "Webhook 群消息推送"
    author = "Jayson"
    version = "1.2.1"

    def __init__(self):
        super().__init__()
        self.plugin_dir = Path(__file__).resolve().parent
        self.config = self._load_config()

        plugin_config = self.config.get("WebhookPush", {})
        self.enable = bool(plugin_config.get("enable", False))
        self.rate_limit_seconds = float(plugin_config.get("rate-limit-seconds", 1))

        self.token_map: dict[str, dict[str, str]] = {}
        self._last_request_at: dict[str, float] = {}
        self._build_token_map(self.config.get("webhooks", []))

    def _load_config(self) -> dict[str, Any]:
        config_path = self.plugin_dir / "config.toml"
        with open(config_path, "rb") as f:
            return tomllib.load(f)

    def _build_token_map(self, webhooks: list[Any]) -> None:
        secured_count = 0
        for item in webhooks:
            if not isinstance(item, dict):
                continue

            token = str(item.get("token", "")).strip()
            group_wxid = str(item.get("group_wxid", "")).strip()
            name = str(item.get("name", "")).strip() or group_wxid
            api_key = str(item.get("api_key", "") or item.get("secret", "")).strip()

            if not token:
                logger.warning("[WebhookPush] 跳过无效 webhook 配置：token 为空")
                continue
            if not group_wxid.endswith("@chatroom"):
                logger.warning(
                    f"[WebhookPush] 跳过 webhook「{name}」：group_wxid 必须以 @chatroom 结尾"
                )
                continue
            if token in self.token_map:
                logger.warning(f"[WebhookPush] 检测到重复 token，后者将覆盖前者: {name}")

            self.token_map[token] = {
                "name": name,
                "group_wxid": group_wxid,
                "api_key": api_key,
            }
            if api_key:
                secured_count += 1

        logger.info(
            f"[WebhookPush] 已加载 {len(self.token_map)} 个 webhook 配置"
            f"（其中 {secured_count} 个启用 api_key 鉴权）"
        )

    @staticmethod
    def _format_message(content: str, from_source: str) -> str:
        if from_source:
            return f"[{from_source}] {content}"
        return content

    @staticmethod
    def _text_char_length(text: str) -> int:
        """估算文本长度：汉字等非 ASCII 按 2 字符，英文符号按 1 字符。"""
        return sum(1 if ord(char) <= 127 else 2 for char in text)

    def _extract_api_key(self, request: Request, payload: dict[str, Any] | None) -> str:
        api_key = (
            request.headers.get("api_key")
            or request.headers.get("api-key")
            or request.headers.get("Api-Key")
            or request.headers.get("apikey")
            or request.headers.get("api")
            or request.headers.get("x-api-key")
            or request.headers.get("X-API-Key")
            or request.headers.get("x-apikey")
            or ""
        ).strip()

        authorization = request.headers.get("Authorization", "").strip()
        if not api_key and authorization.lower().startswith("bearer "):
            api_key = authorization[7:].strip()

        if not api_key:
            api_key = str(request.query_params.get("api_key", "")).strip()
        if not api_key:
            api_key = str(request.query_params.get("api", "")).strip()

        if not api_key and payload is not None:
            api_key = str(
                payload.get("api_key", "")
                or payload.get("api", "")
                or payload.get("API_KEY", "")
            ).strip()

        return api_key

    def _verify_api_key(
        self,
        webhook: dict[str, str],
        request: Request,
        payload: dict[str, Any] | None,
    ) -> JSONResponse | None:
        expected = webhook.get("api_key", "")
        if not expected:
            return None

        api_key = self._extract_api_key(request, payload)
        if not api_key:
            debug = {
                "method": request.method,
                "query_keys": list(request.query_params.keys()),
                "body_keys": list(payload.keys()) if isinstance(payload, dict) else None,
                "header_keys": [k for k in request.headers.keys()],
                "hint": "api_key 没传进来。把它放到 URL 后面 ?api_key=你的密钥 最稳",
            }
            logger.warning(f"[WebhookPush] 缺少 api_key，请求诊断: {debug}")
            return JSONResponse(
                content={"code": 19009, "msg": "api_key required", "debug": debug},
                status_code=401,
            )

        if api_key != expected:
            return self._response(19010, "invalid api_key", status_code=401)

        return None

    async def async_init(self) -> None:
        if not self.enable:
            logger.info("[WebhookPush] 插件未启用，跳过路由注册")
            return
        self._register_routes()

    def _register_routes(self) -> None:
        global _ROUTES_REGISTERED

        if _ROUTES_REGISTERED:
            logger.debug("[WebhookPush] 路由已注册，跳过重复注册")
            return

        try:
            from admin.server import app
        except ImportError:
            logger.warning("[WebhookPush] 无法导入 admin.server，跳过路由注册")
            return

        if app is None:
            logger.warning("[WebhookPush] 管理后台 app 未就绪，跳过路由注册")
            return

        plugin = self

        @app.api_route(
            "/api/webhook/{token}",
            methods=["GET", "POST"],
            response_class=JSONResponse,
            tags=["WebhookPush"],
        )
        async def api_webhook_push(token: str, request: Request):
            return await plugin.handle_webhook(token, request)

        _ROUTES_REGISTERED = True
        logger.success("[WebhookPush] 路由已注册: GET/POST /api/webhook/{token}")

    @staticmethod
    def _response(code: int, msg: str, status_code: int = 200) -> JSONResponse:
        return JSONResponse(content={"code": code, "msg": msg}, status_code=status_code)

    @staticmethod
    def _resolve_client() -> Any | None:
        from admin.core.app_setup import get_bot_instance

        bot = get_bot_instance()
        if bot is None:
            return None
        return getattr(bot, "bot", bot)

    async def handle_webhook(self, token: str, request: Request) -> JSONResponse:
        if not self.enable:
            return self._response(19005, "plugin disabled", status_code=403)

        token = token.strip()
        webhook = self.token_map.get(token)
        if webhook is None:
            return self._response(19001, "invalid token", status_code=401)

        method = request.method.upper()
        payload: dict[str, Any] | None = None

        if method == "POST":
            try:
                raw = await request.json()
            except Exception:
                return self._response(19006, "invalid json", status_code=400)
            if not isinstance(raw, dict):
                return self._response(19006, "invalid json", status_code=400)
            payload = raw
        elif method != "GET":
            return self._response(19012, "method not allowed", status_code=405)

        auth_error = self._verify_api_key(webhook, request, payload)
        if auth_error is not None:
            return auth_error

        if method == "POST" and payload is not None:
            content = str(payload.get("content", "")).strip()
            from_source = str(payload.get("from", "")).strip()
        else:
            content = str(request.query_params.get("content", "")).strip()
            from_source = str(request.query_params.get("from", "")).strip()
            logger.info(
                "[WebhookPush] 收到原始 GET query: "
                f"content={content!r}, from={from_source!r}"
            )

        logger.info(
            "[WebhookPush] 解析消息内容: "
            f"content={content!r}, from={from_source!r}, "
            f"content_text_len={self._text_char_length(content)}"
        )

        if not content:
            return self._response(19007, "content is required", status_code=400)

        client = self._resolve_client()
        if client is None:
            return self._response(19002, "bot not ready", status_code=503)

        send_func = getattr(client, "send_text_message", None)
        if not callable(send_func):
            return self._response(19002, "bot not ready", status_code=503)

        now = time.monotonic()
        last = self._last_request_at.get(token, 0.0)
        if now - last < self.rate_limit_seconds:
            return self._response(19004, "rate limit exceeded", status_code=429)
        self._last_request_at[token] = now

        text = self._format_message(content, from_source)
        text_len = self._text_char_length(text)
        logger.info(
            "[WebhookPush] 准备发送原始文本: "
            f"text={text!r}, text_len={text_len}, limit=4000"
        )
        if text_len > 4000:
            logger.warning(
                "[WebhookPush] 文本长度超过会话消息限制，可能发送失败: "
                f"text_len={text_len}, limit=4000"
            )
        group_wxid = webhook["group_wxid"]
        try:
            if inspect.iscoroutinefunction(send_func):
                await send_func(group_wxid, text, "")
            else:
                send_func(group_wxid, text, "")
        except Exception as e:
            logger.error(f"[WebhookPush] 发送失败（{webhook.get('name')}）: {e}")
            return self._response(19008, f"send failed: {str(e)}", status_code=500)

        logger.info(f"[WebhookPush] 已推送到群「{webhook.get('name')}」: {group_wxid}")
        return self._response(0, "success")
