from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Protocol, cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.engine import LunaEngine


class _TextIoWithReconfigure(Protocol):
    def reconfigure(self, *, encoding: str, errors: str | None = None) -> object: ...


class _BridgeEngine(Protocol):
    memory: Any
    user_settings: Any
    _action_mode_override: str | None

    def get_current_chat_id(self) -> str: ...
    def list_chats(self) -> list[dict[str, str]]: ...
    def get_pending_action_title(self) -> str: ...
    def create_new_chat(self, title: str = "New chat") -> str: ...
    def switch_chat(self, session_id: str) -> list[dict[str, str]]: ...
    def rename_chat(self, session_id: str, title: str) -> str: ...
    def delete_chat(self, session_id: str) -> str: ...
    def chat(self, user_input: str, *, extra_context: str = "") -> str: ...
    def confirm_pending_action(self) -> str: ...
    def cancel_pending_action(self) -> str: ...
    def get_last_coordination(self) -> dict[str, Any]: ...
    def list_recent_agent_trace(self, limit: int = 8) -> list[dict[str, Any]]: ...
    def list_agent_tools(self) -> list[dict[str, Any]]: ...
    def get_agent_run_state(self) -> dict[str, Any]: ...
    def get_observe_mode_enabled(self) -> bool: ...
    def get_last_desktop_observation(self) -> dict[str, Any]: ...
    def set_observe_mode(self, enabled: bool) -> str: ...
    def capture_desktop_snapshot(self, include_screenshot: bool = False, *, remember: bool = True) -> dict[str, Any]: ...
    def read_attachment_context(self, file_paths: list[str]) -> str: ...
    def analyze_visual_media(self, file_paths: list[str], query: str = "") -> dict[str, Any]: ...
    def observe_system_state(
        self,
        *,
        project_root: str = "",
        terminal_output: str = "",
        log_files: list[str] | None = None,
        process_names: list[str] | None = None,
    ) -> dict[str, Any]: ...
    def transcribe_audio_file(self, file_path: str, language: str = "") -> dict[str, Any]: ...
    def synthesize_speech_text(self, text: str, language: str = "", voice: str = "") -> dict[str, Any]: ...


def _message_author(item: dict[str, str]) -> str:
    role = str(item.get("role", "assistant") or "assistant")
    if role == "user":
        return "You"
    author = str(item.get("author", "") or "").strip()
    return author or "Luna"


def _serialize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for index, item in enumerate(history):
        role = str(item.get("role", "assistant") or "assistant")
        content = str(item.get("content", "") or "")
        items.append({
            "id": f"msg-{index}",
            "role": role,
            "author": _message_author(item),
            "content": content,
        })
    return items


def _serialize_chats(chats: list[dict[str, str]], current_chat_id: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for chat in chats:
        chat_id = str(chat.get("id", "") or "")
        items.append({
            "id": chat_id,
            "title": str(chat.get("title", "New Chat") or "New Chat"),
            "pinned": chat_id == current_chat_id,
            "archived": False,
            "kind": "chat",
            "messageCount": int(str(chat.get("message_count", "0") or "0")),
        })
    return items


def _state(engine: _BridgeEngine) -> dict[str, Any]:
    current_chat_id = engine.get_current_chat_id()
    chats = _serialize_chats(engine.list_chats(), current_chat_id)
    messages = _serialize_history(engine.memory.load_history())
    pending_title = engine.get_pending_action_title()
    pending_action = {
        "active": bool(pending_title),
        "title": pending_title,
    }
    return {
        "ok": True,
        "currentChatId": current_chat_id,
        "chats": chats,
        "messages": messages,
        "pendingAction": pending_action,
        "coordination": engine.get_last_coordination(),
        "agentTrace": engine.list_recent_agent_trace(6),
        "agentTools": engine.list_agent_tools(),
        "agentRun": engine.get_agent_run_state(),
        "observeModeEnabled": engine.get_observe_mode_enabled(),
        "lastObservation": engine.get_last_desktop_observation(),
    }


def main() -> int:
    try:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                cast(_TextIoWithReconfigure, stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    action = str(payload.get("action", "state") or "state").strip().lower()
    engine = cast(_BridgeEngine, LunaEngine())

    if action == "state":
        result = _state(engine)
    elif action == "create_chat":
        title = str(payload.get("title", "New chat") or "New chat")
        chat_id = engine.create_new_chat(title)
        result = _state(engine)
        result["createdChatId"] = chat_id
    elif action == "switch_chat":
        chat_id = str(payload.get("chatId", "") or "")
        history = engine.switch_chat(chat_id)
        result = _state(engine)
        result["messages"] = _serialize_history(history)
    elif action == "rename_chat":
        chat_id = str(payload.get("chatId", "") or "")
        title = str(payload.get("title", "") or "")
        engine.rename_chat(chat_id, title)
        result = _state(engine)
    elif action == "delete_chat":
        chat_id = str(payload.get("chatId", "") or "")
        engine.delete_chat(chat_id)
        result = _state(engine)
    elif action == "send_message":
        chat_id = str(payload.get("chatId", "") or "")
        text = str(payload.get("text", "") or "")
        extra_context = str(payload.get("extraContext", "") or "").strip()
        raw_file_paths = payload.get("filePaths", [])
        file_paths = [str(item).strip() for item in raw_file_paths] if isinstance(raw_file_paths, list) else []
        attachment_context = engine.read_attachment_context([path for path in file_paths if path])
        force_action_execution = bool(payload.get("forceActionExecution", False))
        if chat_id:
            engine.switch_chat(chat_id)
        original_mode = engine.user_settings.data.agent_execution_mode
        original_override = engine._action_mode_override
        if force_action_execution:
            engine._action_mode_override = "auto"
        try:
            combined_context = "\n\n".join(
                part for part in [extra_context, attachment_context] if str(part or "").strip()
            )
            response = engine.chat(text, extra_context=combined_context)
        finally:
            engine.user_settings.data.agent_execution_mode = original_mode
            engine._action_mode_override = original_override
        result = _state(engine)
        result["response"] = response
    elif action == "observe_desktop":
        include_screenshot = bool(payload.get("includeScreenshot", False))
        snapshot = engine.capture_desktop_snapshot(include_screenshot=include_screenshot, remember=True)
        result = _state(engine)
        result.update(snapshot)
    elif action == "analyze_visual":
        raw_file_paths = payload.get("filePaths", [])
        file_paths = [str(item).strip() for item in raw_file_paths] if isinstance(raw_file_paths, list) else []
        query = str(payload.get("query", "") or "")
        analysis = engine.analyze_visual_media(file_paths, query=query)
        result = _state(engine)
        result.update(analysis)
    elif action == "observe_system":
        raw_log_files = payload.get("logFiles", [])
        raw_process_names = payload.get("processNames", [])
        log_files = [str(item).strip() for item in raw_log_files] if isinstance(raw_log_files, list) else []
        process_names = [str(item).strip() for item in raw_process_names] if isinstance(raw_process_names, list) else []
        observation = engine.observe_system_state(
            project_root=str(payload.get("projectRoot", "") or ""),
            terminal_output=str(payload.get("terminalOutput", "") or ""),
            log_files=log_files,
            process_names=process_names,
        )
        result = _state(engine)
        result["observation"] = observation
    elif action == "transcribe_audio":
        file_path = str(payload.get("filePath", "") or "")
        language = str(payload.get("language", "") or "")
        transcription = engine.transcribe_audio_file(file_path, language=language)
        result = _state(engine)
        result.update(transcription)
    elif action == "synthesize_speech":
        text = str(payload.get("text", "") or "")
        language = str(payload.get("language", "") or "")
        voice = str(payload.get("voice", "") or "")
        speech = engine.synthesize_speech_text(text, language=language, voice=voice)
        result = _state(engine)
        result.update(speech)
    elif action == "set_observe_mode":
        enabled = bool(payload.get("enabled", False))
        response = engine.set_observe_mode(enabled)
        result = _state(engine)
        result["response"] = response
    elif action == "confirm_pending_action":
        response = engine.confirm_pending_action()
        result = _state(engine)
        result["response"] = response
    elif action == "cancel_pending_action":
        response = engine.cancel_pending_action()
        result = _state(engine)
        result["response"] = response
    else:
        result = {"ok": False, "message": f"Unknown bridge action: {action}"}

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
