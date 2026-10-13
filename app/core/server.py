from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlparse

from app.core.engine import LunaEngine


class SettingsLike(Protocol):
    app_name: str
    host: str
    port: int
    model_type: str


def _default_settings() -> SettingsLike:
    settings_module = import_module("config.settings")
    settings_class = getattr(settings_module, "AppSettings")
    return cast(SettingsLike, settings_class())


class LunaServer:
    def __init__(
        self,
        settings: SettingsLike | None = None,
        engine: LunaEngine | None = None,
    ) -> None:
        self.settings = settings or _default_settings()
        self._engine = engine

    @property
    def engine(self) -> LunaEngine:
        if self._engine is None:
            self._engine = LunaEngine()
        return self._engine

    def status(self) -> dict[str, str | int]:
        return {
            "app": self.settings.app_name,
            "host": self.settings.host,
            "port": self.settings.port,
            "modelType": self.settings.model_type,
        }

    def state(self) -> dict[str, Any]:
        return {
            "status": self.status(),
            "currentChatId": self.engine.get_current_chat_id(),
            "currentChatTitle": self.engine.get_current_chat_title(),
            "chats": self.engine.list_chats(),
            "history": self.engine.memory.load_history(),
            "observeModeEnabled": self.engine.get_observe_mode_enabled(),
            "lastDesktopObservation": self.engine.get_last_desktop_observation(),
        }

    def status_text(self) -> str:
        status = self.status()
        return (
            f"{status['app']} status\n"
            f"host: {status['host']}\n"
            f"port: {status['port']}\n"
            f"model: {status['modelType']}"
        )

    def _json_response(
        self,
        handler: BaseHTTPRequestHandler,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status.value)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    def _read_json_body(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        content_length = int(handler.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        raw_body = handler.rfile.read(content_length)
        if not raw_body:
            return {}
        decoded = raw_body.decode("utf-8").strip()
        if not decoded:
            return {}
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _handle_get(self, path: str, query: dict[str, list[str]]) -> tuple[HTTPStatus, dict[str, Any]]:
        if path == "/":
            return HTTPStatus.OK, {
                "ok": True,
                "message": "LunaAI local API is running.",
                "endpoints": [
                    "GET /status",
                    "GET /state",
                    "GET /chats",
                    "GET /history",
                    "GET /observe?include_screenshot=false&remember=true",
                    "POST /chat",
                    "POST /chats",
                    "POST /chats/switch",
                    "POST /chats/rename",
                    "POST /chats/delete",
                    "POST /history/clear",
                    "POST /observe",
                    "POST /observe-mode",
                    "POST /vision/analyze",
                    "POST /observer/system",
                ],
            }
        if path == "/status":
            return HTTPStatus.OK, {"ok": True, "status": self.status()}
        if path == "/state":
            return HTTPStatus.OK, {"ok": True, "state": self.state()}
        if path == "/chats":
            return HTTPStatus.OK, {
                "ok": True,
                "chats": self.engine.list_chats(),
                "currentChatId": self.engine.get_current_chat_id(),
            }
        if path == "/history":
            return HTTPStatus.OK, {
                "ok": True,
                "history": self.engine.memory.load_history(),
                "currentChatId": self.engine.get_current_chat_id(),
            }
        if path == "/observe":
            include_screenshot = _parse_bool(query.get("include_screenshot", ["false"])[0], default=False)
            remember = _parse_bool(query.get("remember", ["true"])[0], default=True)
            snapshot = self.engine.capture_desktop_snapshot(
                include_screenshot=include_screenshot,
                remember=remember,
            )
            return HTTPStatus.OK, snapshot
        return HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Unknown endpoint: {path}"}

    def _handle_post(self, path: str, payload: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        if path == "/chat":
            user_input = str(payload.get("message", "") or "").strip()
            if not user_input:
                return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Field 'message' is required."}
            extra_context = str(payload.get("extra_context", "") or "")
            response = self.engine.chat(user_input, extra_context=extra_context)
            return HTTPStatus.OK, {
                "ok": True,
                "response": response,
                "currentChatId": self.engine.get_current_chat_id(),
                "history": self.engine.memory.load_history(),
            }
        if path == "/chats":
            title = str(payload.get("title", "New chat") or "New chat")
            session_id = self.engine.create_new_chat(title)
            return HTTPStatus.CREATED, {
                "ok": True,
                "sessionId": session_id,
                "currentChatId": self.engine.get_current_chat_id(),
                "chats": self.engine.list_chats(),
                "history": self.engine.memory.load_history(),
            }
        if path == "/chats/switch":
            session_id = str(payload.get("sessionId", "") or "").strip()
            if not session_id:
                return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Field 'sessionId' is required."}
            history = self.engine.switch_chat(session_id)
            return HTTPStatus.OK, {
                "ok": True,
                "currentChatId": self.engine.get_current_chat_id(),
                "history": history,
                "chats": self.engine.list_chats(),
            }
        if path == "/chats/rename":
            session_id = str(payload.get("sessionId", "") or "").strip()
            title = str(payload.get("title", "") or "")
            if not session_id:
                return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Field 'sessionId' is required."}
            new_title = self.engine.rename_chat(session_id, title)
            return HTTPStatus.OK, {
                "ok": True,
                "sessionId": session_id,
                "title": new_title,
                "chats": self.engine.list_chats(),
            }
        if path == "/chats/delete":
            session_id = str(payload.get("sessionId", "") or "").strip()
            if not session_id:
                return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Field 'sessionId' is required."}
            current_chat_id = self.engine.delete_chat(session_id)
            return HTTPStatus.OK, {
                "ok": True,
                "currentChatId": current_chat_id,
                "chats": self.engine.list_chats(),
                "history": self.engine.memory.load_history(),
            }
        if path == "/history/clear":
            self.engine.clear_history()
            return HTTPStatus.OK, {
                "ok": True,
                "currentChatId": self.engine.get_current_chat_id(),
                "history": self.engine.memory.load_history(),
            }
        if path == "/observe":
            include_screenshot = _parse_bool(payload.get("includeScreenshot"), default=False)
            remember = _parse_bool(payload.get("remember"), default=True)
            snapshot = self.engine.capture_desktop_snapshot(
                include_screenshot=include_screenshot,
                remember=remember,
            )
            return HTTPStatus.OK, snapshot
        if path == "/observe-mode":
            enabled = _parse_bool(payload.get("enabled"), default=False)
            message = self.engine.set_observe_mode(enabled)
            return HTTPStatus.OK, {
                "ok": True,
                "enabled": self.engine.get_observe_mode_enabled(),
                "message": message,
                "lastDesktopObservation": self.engine.get_last_desktop_observation(),
            }
        if path == "/vision/analyze":
            raw_paths = payload.get("filePaths", [])
            file_paths = [str(item).strip() for item in raw_paths] if isinstance(raw_paths, list) else []
            query = str(payload.get("query", "") or "")
            return HTTPStatus.OK, self.engine.analyze_visual_media(file_paths, query=query)
        if path == "/observer/system":
            raw_log_files = payload.get("logFiles", [])
            raw_process_names = payload.get("processNames", [])
            log_files = [str(item).strip() for item in raw_log_files] if isinstance(raw_log_files, list) else []
            process_names = [str(item).strip() for item in raw_process_names] if isinstance(raw_process_names, list) else []
            observation = self.engine.observe_system_state(
                project_root=str(payload.get("projectRoot", "") or ""),
                terminal_output=str(payload.get("terminalOutput", "") or ""),
                log_files=log_files,
                process_names=process_names,
            )
            return HTTPStatus.OK, {"ok": bool(observation.get("ok", False)), "observation": observation}
        return HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Unknown endpoint: {path}"}

    def create_http_server(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> ThreadingHTTPServer:
        server_host = host or self.settings.host
        server_port = self.settings.port if port is None else port
        parent = self

        class LunaRequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                try:
                    status, payload = parent._handle_get(parsed.path, query)
                except Exception as error:
                    parent._json_response(
                        self,
                        {"ok": False, "error": str(error)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                parent._json_response(self, payload, status=status)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                try:
                    payload = parent._read_json_body(self)
                    status, response_payload = parent._handle_post(parsed.path, payload)
                except ValueError as error:
                    parent._json_response(
                        self,
                        {"ok": False, "error": str(error)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                except Exception as error:
                    parent._json_response(
                        self,
                        {"ok": False, "error": str(error)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                parent._json_response(self, response_payload, status=status)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return ThreadingHTTPServer((server_host, server_port), LunaRequestHandler)

    def run(self) -> None:
        http_server = self.create_http_server()
        server_address = http_server.server_address
        host = str(server_address[0])
        port = int(server_address[1])
        print(f"{self.settings.app_name} local API listening on http://{host}:{port}")
        try:
            http_server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping LunaAI local API...")
        finally:
            http_server.server_close()


def _parse_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
