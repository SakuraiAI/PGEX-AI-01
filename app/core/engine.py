from __future__ import annotations

from pathlib import Path
from typing import Callable, Any, Mapping
from collections import OrderedDict
import json
import os
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.settings import AppSettings
from app.core.action_log import ActionLogStore
from app.core.agent_action_router import AgentActionRouter, AgentRoute
from app.core.agent_loop import AgentLoopResult, AgentLoopStep
from app.core.agent_run_state import AgentRunStateStore
from app.core.agent_tool_registry import AgentToolRegistry, ToolSpec
from app.core.agent_trace import AgentTraceStore
from app.core.agent_orchestrator import AgentOrchestrator
from app.core.library_store import LibraryStore
from app.core.memory_coordinator import MemoryCoordinator
from app.core.observer_layer import ObserverLayer
from app.core.system_control import SystemControlLayer
from app.core.prompt_builder import PromptBuilder
from app.core.project_store import ProjectStore
from app.core.runtime_status import RuntimeStatusFormatter
from app.tools.app_discovery import find_registered_app
from app.core.user_settings import UserSettingsStore
from app.core.vision_layer import VisionLayer
from app.memory.chat_memory import ChatMemory
from app.memory.long_memory import LongMemory
from app.models.local_model import LocalModel
from app.models.nvidia_model import NvidiaModel
from app.models.nvidia_speech_model import NvidiaSpeechModel
from app.models.nvidia_tts_model import NvidiaTtsModel
from app.models.nvidia_vision_model import NvidiaVisionModel
from app.tools.desktop_actions import DesktopActionTool
from app.tools.desktop_observer import DesktopObserverTool
from app.tools.internet import InternetTool
from app.workflow.manager import WorkflowManager
from app.xeno.coordinator import XenoCoordinator
from app.core.text_utils import ascii_fold_text, repair_text


class LunaEngine:
    def __init__(self) -> None:
        self.settings = AppSettings()
        self.settings.ensure_directories()
        if self.settings.model_type == "nvidia":
            self.model = NvidiaModel(
                model_name=self.settings.luna_nvidia_model,
                base_url=self.settings.luna_nvidia_base_url,
                api_token=self.settings.luna_nvidia_api_token,
                timeout_seconds=self.settings.luna_nvidia_timeout_seconds,
                reasoning_budget=self.settings.nvidia_reasoning_budget,
                enable_thinking=self.settings.nvidia_enable_thinking,
            )
        else:
            self.model = LocalModel(
                model_name=self.settings.lm_studio_model,
                base_url=self.settings.lm_studio_base_url,
                provider="lm_studio",
                api_token=self.settings.lm_studio_api_token,
                timeout_seconds=self.settings.lm_studio_timeout_seconds,
            )
        self.support_model = NvidiaModel(
            model_name=self.settings.nvidia_model,
            base_url=self.settings.nvidia_base_url,
            api_token=self.settings.nvidia_api_token,
            timeout_seconds=self.settings.nvidia_timeout_seconds,
            reasoning_budget=self.settings.nvidia_reasoning_budget,
            enable_thinking=self.settings.nvidia_enable_thinking,
        )
        self.vision_model = NvidiaVisionModel(
            model_name=self.settings.vision_nvidia_model,
            base_url=self.settings.vision_nvidia_base_url,
            api_token=self.settings.vision_nvidia_api_token,
            timeout_seconds=self.settings.vision_nvidia_timeout_seconds,
        )
        self.speech_model = NvidiaSpeechModel(
            model_name=self.settings.speech_nvidia_model,
            base_url=self.settings.speech_nvidia_base_url,
            api_token=self.settings.speech_nvidia_api_token,
            server=self.settings.speech_nvidia_server,
            function_id=self.settings.speech_nvidia_function_id,
            use_ssl=self.settings.speech_nvidia_use_ssl,
            timeout_seconds=self.settings.speech_nvidia_timeout_seconds,
            language=self.settings.speech_nvidia_language,
        )
        self.tts_model = NvidiaTtsModel(
            model_name=self.settings.tts_nvidia_model,
            api_token=self.settings.tts_nvidia_api_token,
            server=self.settings.tts_nvidia_server,
            function_id=self.settings.tts_nvidia_function_id,
            use_ssl=self.settings.tts_nvidia_use_ssl,
            timeout_seconds=self.settings.tts_nvidia_timeout_seconds,
            language=self.settings.tts_nvidia_language,
            voice=self.settings.tts_nvidia_voice,
            sample_rate_hz=self.settings.tts_nvidia_sample_rate,
        )
        self.memory = ChatMemory(Path(self.settings.memory_path))
        self.long_memory = LongMemory(Path(self.settings.long_memory_path))
        self.workflow = WorkflowManager()
        self.internet = InternetTool()
        self.desktop_actions = DesktopActionTool()
        self.desktop_observer = DesktopObserverTool()
        self.vision_layer = VisionLayer(self.vision_model)
        self.observer_layer = ObserverLayer()
        self.xeno = XenoCoordinator()
        self.user_settings = UserSettingsStore(Path(self.settings.user_settings_path))
        self.projects = ProjectStore(Path(self.settings.projects_path))
        self.library = LibraryStore(Path(self.settings.library_path))
        self.action_log = ActionLogStore(Path("data/logs/action_log.jsonl"))
        self.agent_trace = AgentTraceStore(Path("data/logs/agent_trace.jsonl"))
        self.agent_run_state = AgentRunStateStore(Path("data/logs/agent_run_state.json"))
        self.system_control = SystemControlLayer()
        self.system_control.apply_profile(self.user_settings.data, self.user_settings.data.system_control_profile)
        self.orchestrator = AgentOrchestrator()
        self.agent_router = AgentActionRouter()
        self.tool_registry = AgentToolRegistry()
        self.pending_action: tuple[str, str, Callable[[], object]] | None = None
        self.pending_action_plan: dict[str, object] | None = None
        self._active_agent_route: AgentRoute | None = None
        self._action_mode_override: str | None = None
        self.observe_mode_enabled = False
        self.last_desktop_observation: dict[str, object] | None = None
        self.live_screen_summary: str = ""
        self.last_model_debug = ""
        self._last_support_model_source = "unused"
        self._last_primary_model_source = "nvidia" if self.settings.model_type == "nvidia" else "lm_studio"
        self.last_coordination = {
            "lunaActive": False,
            "xenoActive": False,
            "tracks": [],
        }

        try:
            timezone = ZoneInfo("Europe/Prague")
            timezone_name = "Europe/Prague"
        except ZoneInfoNotFoundError:
            timezone = None
            timezone_name = "local system time"

        self.prompt_builder = PromptBuilder(
            memory=self.memory,
            long_memory=self.long_memory,
            internet=self.internet,
            timezone=timezone,
            timezone_name=timezone_name,
        )
        self.memory_coordinator = MemoryCoordinator(
            chat_memory=self.memory,
            long_memory=self.long_memory,
            review_interval=self.settings.memory_review_interval,
        )
        self.runtime_status = RuntimeStatusFormatter(
            settings=self.settings,
            internet=self.internet,
        )
        self._apply_runtime_limits()

    def _serialize_project(self, record: Any) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "id": record.id,
            "name": record.name,
            "brief": record.brief,
            "blueprint_text": record.blueprint_text,
            "next_step": record.next_step,
            "current_phase": record.current_phase,
            "handoff_summary": getattr(record, "handoff_summary", ""),
            "tasks": list(record.tasks),
            "memory_entries": list(record.memory_entries),
            "decisions": list(record.decisions),
            "attachment_names": list(record.attachment_names),
        }

    def _normalized_intelligence_level(self) -> str:
        level = str(getattr(self.user_settings.data, "intelligence_level", "4") or "4").strip()
        return level if level in {"3", "4", "5"} else "4"


    def _clamp_percent(self, value: Any, fallback: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = int(fallback)
        return max(10, min(100, parsed))

    def _runtime_limits(self) -> dict[str, int]:
        workspace = self.user_settings.data
        return {
            "cpu": self._clamp_percent(getattr(workspace, "cpu_limit_percent", 55), 55),
            "gpu": self._clamp_percent(getattr(workspace, "gpu_limit_percent", 60), 60),
            "memory": self._clamp_percent(getattr(workspace, "memory_limit_percent", 50), 50),
        }

    def _runtime_budget_profile(self) -> dict[str, Any]:
        limits = self._runtime_limits()
        headroom = min(limits["cpu"], limits["gpu"], limits["memory"])
        profile = "balanced"
        if headroom <= 35:
            profile = "constrained"
        elif headroom <= 55:
            profile = "guarded"
        elif headroom >= 80:
            profile = "expanded"
        return {
            "limits": limits,
            "headroom": headroom,
            "profile": profile,
            "xeno_model_support": headroom > 40,
            "observer_live_refresh": headroom > 45,
            "agent_chain_steps": 1 if headroom <= 35 else 2 if headroom <= 60 else 3,
        }

    def _apply_runtime_limits(self) -> None:
        limits = self._runtime_limits()
        self.model.configure_runtime_limits(
            cpu_limit_percent=limits["cpu"],
            gpu_limit_percent=limits["gpu"],
            memory_limit_percent=limits["memory"],
        )

    def _reload_runtime_preferences(self) -> None:
        self.user_settings.load()
        self.system_control.apply_profile(self.user_settings.data, self.user_settings.data.system_control_profile)
        self._apply_runtime_limits()

    def _observer_refresh_enabled(self) -> bool:
        return bool(self._runtime_budget_profile()["observer_live_refresh"])

    def _agent_chain_budget(self, requested_steps: int) -> int:
        budget = int(self._runtime_budget_profile()["agent_chain_steps"])
        return max(1, min(int(requested_steps), budget))

    def _handle_internet_command(self, user_input: str) -> str | None:
        command = user_input.strip().lower()
        if command == "/internet on":
            self.internet.set_enabled(True)
            return "Luna: Internet jsem zapnula. 🌐"
        if command == "/internet off":
            self.internet.set_enabled(False)
            return "Luna: Internet jsem vypnula."
        if command == "/internet auto":
            self.internet.set_enabled(True)
            self.internet.set_mode("auto")
            return "Luna: Internet necham na automatice. 🙂"
        if command == "/internet manual":
            self.internet.set_mode("manual")
            return "Luna: Internet je ted jen rucne."
        if command == "/internet status":
            return self.internet.status()
        if user_input.startswith("/search "):
            query = user_input[8:].strip()
            if not query:
                return "Luna: Chybi mi dotaz pro hledani."
            return self.internet.search(query)
        return None

    def _internet_context(self, user_input: str) -> str:
        if not self.internet.should_search(user_input):
            return ""
        result = self.internet.search(user_input)
        if result.startswith("Luna:"):
            return result[5:].strip()
        return result

    def _hidden_xeno_support(self, user_input: str) -> str:
        if not self.xeno.should_consult(user_input):
            return ""
        level = self._normalized_intelligence_level()
        profile = self._runtime_budget_profile()
        parts = [self.xeno.build_hidden_support(user_input, intelligence_level=level)]
        if bool(profile["xeno_model_support"]):
            model_support = self.xeno.build_model_support(user_input, self._support_generate, intelligence_level=level)
            if model_support:
                parts.append("Hidden Xeno model guidance:\n" + model_support)
        return "\n".join(part for part in parts if part.strip())

    def _compact_coordination_text(self, text: str, limit: int = 180) -> str:
        cleaned = repair_text(str(text or "")).strip()
        replacements = [
            "Hidden Xeno support:",
            "Hidden Xeno automation:",
            "Hidden Xeno risk notes:",
            "Hidden Xeno handoff:",
            "Hidden Xeno model guidance:",
            "Xeno model guidance:",
            "Xeno automation:",
        ]
        for item in replacements:
            cleaned = cleaned.replace(item, "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\n\t")
        if len(cleaned) > limit:
            cleaned = cleaned[: limit - 1].rstrip() + "…"
        return cleaned

    def _build_internal_coordination(
        self,
        *,
        user_input: str,
        response_author: str,
        xeno_consulted: bool,
        automation_summary: str,
        hidden_support: str,
    ) -> dict[str, object]:
        luna_active = response_author == "Luna"
        xeno_active = response_author == "Xeno" or xeno_consulted
        tracks: list[dict[str, str]] = []

        if response_author == "Luna":
            luna_note = "Drzim primou odpoved a skladam ji v kontextu uzivatele."
            if xeno_active:
                luna_note = (
                    "Predavam Xeno strategic check pro: "
                    + (self._compact_coordination_text(user_input, 120) or "aktualni dotaz.")
                )
            tracks.append({
                "speaker": "Luna",
                "title": "Luna",
                "note": luna_note,
            })

        if response_author == "Xeno":
            xeno_note = (
                self._compact_coordination_text(hidden_support or automation_summary or user_input, 170)
                or "Prebiram reasoning vrstvu a odpovidam napriamo."
            )
            tracks.append({
                "speaker": "Xeno",
                "title": "Xeno direct",
                "note": xeno_note,
            })
        elif xeno_active:
            xeno_note = (
                self._compact_coordination_text(hidden_support or automation_summary, 170)
                or "Drzim rizika, architekturu a dalsi nejlepsi krok."
            )
            tracks.append({
                "speaker": "Xeno",
                "title": "Xeno -> Luna",
                "note": xeno_note,
            })

        return {
            "lunaActive": luna_active,
            "xenoActive": xeno_active,
            "tracks": tracks,
        }

    def _format_coordination_prompt(self, coordination: dict[str, object]) -> str:
        if not bool(coordination.get("lunaActive")) or not bool(coordination.get("xenoActive")):
            return ""
        tracks = coordination.get("tracks", [])
        if not isinstance(tracks, list):
            return ""
        luna_note = ""
        xeno_note = ""
        for item in tracks:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker", "")).strip()
            note = str(item.get("note", "")).strip()
            if speaker == "Luna" and not luna_note:
                luna_note = note
            if speaker == "Xeno" and not xeno_note:
                xeno_note = note
        if not luna_note or not xeno_note:
            return ""
        return (
            "Internal coordination:\n"
            f"Luna -> Xeno: {luna_note}\n"
            f"Xeno -> Luna: {xeno_note}"
        )

    def _support_generate(self, messages: list[dict[str, str]]) -> str:
        if self.support_model.is_available():
            try:
                self._last_support_model_source = "nvidia"
                return self.support_model.generate(messages)
            except Exception:
                self._last_support_model_source = "lm_studio_fallback"
        else:
            self._last_support_model_source = "lm_studio_fallback"
        return self.model.generate(messages)

    def _generate_xeno_response(self, messages: list[dict[str, str]]) -> str:
        inherited_system_context = [
            str(item.get("content", "")).strip()
            for item in messages
            if str(item.get("role", "")).strip().lower() == "system" and str(item.get("content", "")).strip()
        ]
        xeno_messages = [
            {
                "role": "system",
                "content": (
                "You are XenoAI, Luna's reasoning layer. "
                "Speak directly in Czech, be strategic, compact, clear, and grounded. "
                "Sound like an experienced technical partner, not a generic assistant. "
                "Do not greet unless the user greeted first. "
                "Do not expose internal reasoning or system notes. "
                "Never present guesses as verified facts. "
                "If you summarize project status, distinguish verified local state, visible on-screen context, and uncertain inference. "
                "Do not invent files, commands, successful runs, or project structure unless they are present in trusted context. "
                "Use the same trusted context priority as Luna: confirmed action results, newest live desktop frame, active project, long-term memory, then older chat. "
                "When the user asks Xeno directly, answer as Xeno but still stay inside the same LunaAI platform and use shared screen/project context. "
                "Use emoji occasionally and naturally, especially in short human replies. "
                "For technical answers keep them restrained, usually zero or one. "
                "Prefer calm emoji such as 🙂, ✨, 👀, or 🌙, and never overdo it. "
                "Use the inherited hidden support, live screen context, attachment analysis, and current conversation context as trusted input."
            ),
        },
            *[
                {"role": "system", "content": content}
                for content in inherited_system_context
            ],
            *[item for item in messages if str(item.get("role", "")).strip().lower() != "system"],
        ]
        if self.support_model.is_available():
            try:
                self._last_support_model_source = "nvidia"
                return self.support_model.generate(xeno_messages)
            except Exception:
                self._last_support_model_source = "luna_fallback"
        try:
            self._last_primary_model_source = "nvidia_fallback"
            return self.model.generate(xeno_messages)
        except Exception as exc:
            self._last_support_model_source = "nvidia_error"
            return f"Xeno: Ted se mi nepodarilo pripojit reasoning vrstvu. Zkus to prosim za chvili znovu 🙂 Details: {exc}"

    def _is_local_model_failure(self, response: str) -> bool:
        lowered = str(response or "").strip().lower()
        failure_signals = [
            "luna: lm studio is not reachable",
            "luna: lm studio returned http",
            "luna: lm studio accepted the connection but closed it without a response",
            "luna: lm studio took too long to answer",
            "luna: invalid response from local model",
            "luna: unexpected local model error",
        ]
        return any(lowered.startswith(signal) for signal in failure_signals)

    def _primary_model_name(self) -> str:
        if self.settings.model_type == "nvidia":
            return self.settings.luna_nvidia_model
        return self.settings.lm_studio_model

    def _generate_primary_response(self, messages: list[dict[str, str]]) -> str:
        if self.settings.model_type == "nvidia":
            try:
                self._last_primary_model_source = "nvidia"
                return self.model.generate(messages)
            except Exception as exc:
                self._last_primary_model_source = "nvidia_error"
                return f"Luna: Ted se mi nepodarilo spojit s NVIDIA API. Zkus to prosim za chvili znovu 🌐 Details: {exc}"

        self._last_primary_model_source = "lm_studio"
        response = self.model.generate(messages)
        if not self._is_local_model_failure(response):
            return response
        if not self.support_model.is_available():
            self._last_primary_model_source = "lm_studio_error"
            return response
        try:
            fallback_response = str(self.support_model.generate(messages) or "").strip()
        except Exception:
            self._last_primary_model_source = "lm_studio_error"
            return response
        if fallback_response:
            self._last_primary_model_source = "nvidia_fallback"
            return fallback_response
        self._last_primary_model_source = "lm_studio_error"
        return response

    def _build_model_debug_footer(self, *, xeno_consulted: bool) -> str:
        source_map = {
            "nvidia": "NVIDIA",
            "lm_studio_fallback": "LM Studio fallback",
            "unused": "nepouzito",
            "lm_studio": "LM Studio",
            "nvidia_fallback": "NVIDIA fallback",
            "lm_studio_error": "LM Studio error",
            "nvidia_error": "NVIDIA error",
        }
        support_source = source_map.get(self._last_support_model_source, self._last_support_model_source or "nepouzito")
        primary_source = source_map.get(self._last_primary_model_source, self._last_primary_model_source or "LM Studio")
        consulted = "ano" if xeno_consulted else "ne"
        return (
            "[Model debug]\n"
            f"Luna model: {self._primary_model_name()}\n"
            f"Luna source: {primary_source}\n"
            f"Xeno model: {self.settings.nvidia_model}\n"
            f"Xeno consulted: {consulted}\n"
            f"Xeno source: {support_source}"
        )

    def _requested_speaker(self, user_input: str) -> str | None:
        normalized = str(user_input or "").strip().lower()
        if not normalized:
            return None
        if re.search(r"\blun(a|o|ai)\b", normalized):
            return "Luna"
        if re.search(r"\bxeno(ai)?\b", normalized):
            return "Xeno"
        return None

    def _current_conversation_speaker(self) -> str:
        history = self.memory.load_history()
        for item in reversed(history):
            if str(item.get("role", "")).strip().lower() != "assistant":
                continue
            author = str(item.get("author", "")).strip()
            if author in {"Luna", "Xeno"}:
                return author
        return "Luna"

    def _response_author(self, user_input: str, *, xeno_consulted: bool) -> str:
        requested_speaker = self._requested_speaker(user_input)
        if requested_speaker is not None:
            return requested_speaker
        return self._current_conversation_speaker()

    def get_last_coordination(self) -> dict[str, object]:
        tracks = self.last_coordination.get("tracks", [])
        normalized_tracks: list[dict[str, str]] = []
        if isinstance(tracks, list):
            for item in tracks:
                if not isinstance(item, dict):
                    continue
                normalized_tracks.append({
                    "speaker": str(item.get("speaker", "")).strip(),
                    "title": str(item.get("title", "")).strip(),
                    "note": str(item.get("note", "")).strip(),
                })
        return {
            "lunaActive": bool(self.last_coordination.get("lunaActive")),
            "xenoActive": bool(self.last_coordination.get("xenoActive")),
            "tracks": normalized_tracks,
        }

    def _action_mode(self) -> str:
        override = str(self._action_mode_override or "").strip().lower()
        if override in {"ask", "auto", "block"}:
            return override
        mode = str(self.user_settings.data.agent_execution_mode or "auto").strip().lower()
        if mode not in {"ask", "auto", "block"}:
            return "auto"
        return mode

    def _is_action_allowed(self, category: str) -> bool:
        workspace = self.user_settings.data
        if category == "app_launch":
            return bool(workspace.allow_app_launch)
        if category == "path_open":
            return bool(workspace.allow_path_open)
        if category == "file_read":
            return bool(workspace.allow_path_open)
        if category == "file_change":
            return bool(workspace.allow_file_changes)
        if category == "dependency_install":
            return bool(workspace.allow_file_changes)
        if category == "project_run":
            return bool(workspace.allow_app_launch)
        if category == "system_input":
            return bool(workspace.allow_app_launch)
        return True

    def _log_action(self, category: str, title: str, status: str, detail: str) -> None:
        self.action_log.record(category=category, title=title, status=status, detail=detail)

    def _trace_agent(
        self,
        *,
        phase: str,
        status: str,
        detail: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        route = self._active_agent_route
        self.agent_trace.record(
            phase=phase,
            status=status,
            source=route.input_source if route is not None else "unknown",
            scope=route.action_scope if route is not None else "unknown",
            risk=route.risk if route is not None else "none",
            vision_active=bool(route.vision_active) if route is not None else False,
            xeno_active=bool(route.consult_xeno) if route is not None else False,
            detail=detail,
            metadata=metadata,
        )

    def list_recent_agent_trace(self, limit: int = 8) -> list[dict[str, object]]:
        return [
            {
                "timestamp": entry.timestamp,
                "phase": entry.phase,
                "status": entry.status,
                "source": entry.source,
                "scope": entry.scope,
                "risk": entry.risk,
                "visionActive": entry.vision_active,
                "xenoActive": entry.xeno_active,
                "detail": entry.detail,
                "metadata": entry.metadata,
            }
            for entry in self.agent_trace.recent(limit)
        ]

    def format_agent_trace_status(self, limit: int = 8) -> str:
        route = self._active_agent_route
        current = "No active route right now."
        if route is not None:
            current = (
                f"Current route: source={route.input_source}, scope={route.action_scope}, "
                f"risk={route.risk}, vision={'yes' if route.vision_active else 'no'}, "
                f"xeno={'yes' if route.consult_xeno else 'no'}."
            )
        return current + "\n\n" + self.agent_trace.format_recent(limit)

    def _tool_for_action(self, category: str, title: str) -> ToolSpec | None:
        route = self._active_agent_route
        return self.tool_registry.match(
            category=category,
            title=title,
            user_input=route.user_input if route is not None else title,
        )

    def list_agent_tools(self) -> list[dict[str, object]]:
        return self.tool_registry.to_bridge_payload()

    def format_agent_tools_status(self) -> str:
        return self.tool_registry.format_for_chat()

    def get_agent_run_state(self) -> dict[str, object]:
        return self.agent_run_state.to_payload()

    def format_agent_run_state(self) -> str:
        return self.agent_run_state.format_current()

    def _configured_connected_apps(self) -> list[str]:
        workspace = self.user_settings.data
        app_fields = OrderedDict([
            ("VS Code", workspace.vscode_path),
            ("Google Chrome", workspace.chrome_path),
            ("Blender", workspace.blender_path),
            ("Unreal Engine 5", workspace.unreal_engine_path),
            ("Unity", workspace.unity_path),
            ("Photoshop", workspace.photoshop_path),
            ("DaVinci Resolve", workspace.davinci_resolve_path),
            ("Premiere Pro", workspace.premiere_pro_path),
            ("After Effects", workspace.after_effects_path),
            ("Figma", workspace.figma_path),
            ("FL Studio", workspace.fl_studio_path),
            ("Substance 3D Painter", workspace.substance_painter_path),
        ])
        return [name for name, path in app_fields.items() if str(path).strip()]

    def describe_local_capabilities(self) -> str:
        workspace = self.user_settings.data
        runtime = self._runtime_budget_profile()
        limits: dict[str, int] = runtime.get("limits", {})  # type: ignore
        lines = [
            "Luna local control overview:",
            f"System control profile: {workspace.system_control_profile}",
            f"Agent execution mode: {workspace.agent_execution_mode}",
            f"Runtime profile: {runtime['profile']}",
            f"Runtime limits -> CPU {limits.get('cpu', 0)}% | GPU {limits.get('gpu', 0)}% | Memory {limits.get('memory', 0)}%",
            f"App launch: {'enabled' if workspace.allow_app_launch else 'blocked'}",
            f"Path open: {'enabled' if workspace.allow_path_open else 'blocked'}",
            f"File changes: {'enabled' if workspace.allow_file_changes else 'blocked'}",
        ]
        connected_apps = self._configured_connected_apps()
        if connected_apps:
            lines.append("Connected apps: " + ", ".join(connected_apps))
        else:
            lines.append("Connected apps: none yet")
        lines.append("Registered agent tools: " + ", ".join(self.tool_registry.names()))
        lines.extend([
            "Local actions Luna can handle right now:",
            "- keep an AIQ-inspired agent trace for route, Xeno checks, actions, and verification",
            "- keep an OpenAI Agents-inspired run state with owner, tool, approval, and final result",
            "- observe the active desktop window and mouse position",
            "- compare the current desktop with the previous observation",
            "- keep an observe mode baseline for Luna and Xeno",
            "- capture a screenshot when a backend is available",
            "- open connected apps and workspaces",
            "- open files and folders",
            "- list folders and read text files",
            "- find files and folders in bounded local search roots",
            "- open Chrome/browser URLs and web searches",
            "- press keyboard shortcuts, type text, and click exact coordinates after confirmation",
            "- verify completed actions by observing the desktop state after execution",
            "- create folders and files",
            "- overwrite or append file content",
            "- scaffold python, web, and electron projects",
            "- run agent task actions from project flow",
            "Registered task actions: " + ", ".join(item["action_key"] for item in self.desktop_actions.list_registered_actions()),
        ])
        return "\n".join(lines)

    def _remember_observation(self, observation: dict[str, object], *, source: str = "observe") -> None:
        self.last_desktop_observation = observation
        visual_summary = str(observation.get("vision_summary", "") or "").strip()
        if visual_summary:
            self.live_screen_summary = visual_summary
        project = self.projects.get_current_project()
        if project is None:
            return
        app_label = str(observation.get("app_label", "") or "Desktop app").strip()
        activity = str(observation.get("inferred_activity", "") or "desktop activity").strip()
        title = str(observation.get("active_window_title", "") or "").strip()
        note = f"Desktop observe: {app_label} -> {activity}"
        if title:
            note += f" | {title[:120]}"
        if observation.get("vision_summary"):
            note += " | visual context captured"
        self.projects.add_memory_entry(project.id, note)

    def _observer_context(self, *, refresh: bool = False) -> str:
        if refresh or self.last_desktop_observation is None:
            try:
                observation = self.desktop_observer.observe(include_screenshot=False)
            except Exception:
                observation = None
            if observation is not None:
                self.last_desktop_observation = observation
        observation = self.last_desktop_observation
        if not observation:
            return ""
        lines = [
            "Desktop observer context:",
            f"Active window: {observation.get('active_window_title') or 'unknown'}",
            f"App: {observation.get('app_label') or 'unknown'}",
            f"Meaning: {observation.get('inferred_activity') or 'unknown activity'}",
        ]
        if observation.get("url_hint"):
            lines.append(f"Detected context: {observation.get('url_hint')}")
        if observation.get("screenshot_path"):
            lines.append("User explicitly shared a fresh desktop screenshot for this context.")
        if observation.get("vision_summary"):
            lines.append(f"Vision summary: {observation.get('vision_summary')}")
        return "\n".join(lines)

    def _vision_prompt_for_desktop(self) -> str:
        return (
            "Analyze this one-shot screenshot for LunaAI. Focus on visible UI, readable text, "
            "visible errors, important context, confidence, and the next safe step. Return structured JSON."
        )

    def _analyze_visual_structured(self, file_paths: list[str], query: str, source: str = "") -> dict[str, object]:
        cleaned_paths = [str(path).strip() for path in file_paths if str(path).strip()]
        if not cleaned_paths:
            return self.vision_layer.analyze([], query=query, source=source)
        return self.vision_layer.analyze(cleaned_paths, query=query, source=source)

    def _analyze_visual_media(self, file_paths: list[str], query: str) -> str:
        analysis = self._analyze_visual_structured(file_paths, query=query)
        if not analysis.get("ok"):
            return ""
        return self.vision_layer.summarize(analysis)

    @staticmethod
    def _safe_timestamp_slug() -> str:
        return str(int(time.time() * 1000))

    def analyze_visual_media(self, file_paths: list[str], query: str = "") -> dict[str, object]:
        cleaned_paths = [str(path).strip() for path in file_paths if str(path).strip()]
        analysis = self._analyze_visual_structured(
            cleaned_paths,
            query.strip() or "Describe the visible scene, UI, text, and the most relevant activity on screen.",
        )
        summary = self.vision_layer.summarize(analysis)
        return {
            "ok": bool(analysis.get("ok")),
            "summary": summary,
            "analysis": analysis,
            "files": cleaned_paths,
        }

    def transcribe_audio_file(self, file_path: str, language: str = "") -> dict[str, object]:
        cleaned_path = str(file_path or "").strip()
        if not cleaned_path:
            return {
                "ok": False,
                "transcript": "",
                "message": "Missing audio file path.",
            }
        if not self.speech_model.is_available():
            return {
                "ok": False,
                "transcript": "",
                "message": "NVIDIA speech-to-text is not configured.",
            }
        try:
            transcript = self.speech_model.transcribe_audio(cleaned_path, language=language or self.settings.speech_nvidia_language)
        except Exception as error:
            return {
                "ok": False,
                "transcript": "",
                "message": str(error),
                "file": cleaned_path,
            }
        return {
            "ok": True,
            "transcript": transcript,
            "message": "Speech transcription completed.",
            "file": cleaned_path,
        }

    def synthesize_speech_text(self, text: str, language: str = "", voice: str = "") -> dict[str, object]:
        cleaned_text = str(text or "").strip()
        if not cleaned_text:
            return {
                "ok": False,
                "audioPath": "",
                "message": "Missing text for text-to-speech.",
            }
        if not self.tts_model.is_available():
            return {
                "ok": False,
                "audioPath": "",
                "message": "NVIDIA text-to-speech is not configured.",
            }

        output_dir = Path(self.settings.tts_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"tts_{self._safe_timestamp_slug()}.wav"
        requested_language = language or self.settings.tts_nvidia_language
        requested_voice = voice or self.settings.tts_nvidia_voice
        try:
            audio_path = self.tts_model.synthesize_to_file(
                cleaned_text,
                output_path,
                language=requested_language,
                voice=requested_voice,
            )
        except Exception as error:
            fallback_language = self.settings.tts_nvidia_language
            if requested_language and requested_language != fallback_language:
                try:
                    audio_path = self.tts_model.synthesize_to_file(
                        cleaned_text,
                        output_path,
                        language=fallback_language,
                        voice=requested_voice,
                    )
                    return {
                        "ok": True,
                        "audioPath": str(audio_path),
                        "message": f"Text-to-speech audio generated with fallback language {fallback_language}.",
                    }
                except Exception:
                    pass
            return {
                "ok": False,
                "audioPath": "",
                "message": str(error),
            }
        return {
            "ok": True,
            "audioPath": str(audio_path),
            "message": "Text-to-speech audio generated.",
        }

    def get_observe_mode_enabled(self) -> bool:
        return bool(self.observe_mode_enabled)

    def get_last_desktop_observation(self) -> dict[str, object]:
        return dict(self.last_desktop_observation or {})

    def capture_desktop_snapshot(self, include_screenshot: bool = False, *, remember: bool = True) -> dict[str, object]:
        self._reload_runtime_preferences()
        observation = self.desktop_observer.observe(include_screenshot=include_screenshot)
        screenshot_path = str(observation.get("screenshot_path", "") or "").strip()
        if include_screenshot and screenshot_path:
            vision_analysis = self._analyze_visual_structured(
                [screenshot_path],
                self._vision_prompt_for_desktop(),
                source="screenshot",
            )
            vision_summary = self.vision_layer.summarize(vision_analysis) if vision_analysis.get("ok") else ""
            if vision_summary:
                observation["vision_analysis"] = vision_analysis
                observation["vision_summary"] = vision_summary
        self.last_desktop_observation = observation
        summary = self.desktop_observer.summarize(observation)
        if observation.get("vision_summary"):
            summary = f"{summary}\n\nVision summary:\n{observation.get('vision_summary')}"
        context = self._observer_context(refresh=False)
        source = "desktop screenshot" if include_screenshot else "desktop observe"
        detail = str(observation.get("inferred_activity", "") or observation.get("detail", "")).strip()
        self._log_action("observe", source, "completed", detail)
        if remember:
            self._remember_observation(observation, source=source)
        return {
            "ok": True,
            "summary": summary,
            "context": context,
            "observation": observation,
            "observeModeEnabled": self.observe_mode_enabled,
        }

    def observe_desktop(self, include_screenshot: bool = False, *, remember: bool = True) -> str:
        self._reload_runtime_preferences()
        observation = self.desktop_observer.observe(include_screenshot=include_screenshot)
        screenshot_path = str(observation.get("screenshot_path", "") or "").strip()
        if include_screenshot and screenshot_path:
            vision_analysis = self._analyze_visual_structured(
                [screenshot_path],
                self._vision_prompt_for_desktop(),
                source="screenshot",
            )
            vision_summary = self.vision_layer.summarize(vision_analysis) if vision_analysis.get("ok") else ""
            if vision_summary:
                observation["vision_analysis"] = vision_analysis
                observation["vision_summary"] = vision_summary
        summary = self.desktop_observer.summarize(observation)
        if observation.get("vision_summary"):
            summary = f"{summary}\n\nVision summary:\n{observation.get('vision_summary')}"
        title = "desktop screenshot" if include_screenshot else "desktop observe"
        detail = str(observation.get("inferred_activity", "")).strip() or str(observation.get("detail", ""))
        self._log_action("observe", title, "completed", detail)
        if remember:
            self._remember_observation(observation, source=title)
        return summary

    def diff_desktop_observation(self, include_screenshot: bool = False) -> str:
        self._reload_runtime_preferences()
        previous = self.last_desktop_observation
        current = self.desktop_observer.observe(include_screenshot=include_screenshot)
        diff = self.desktop_observer.diff(previous, current)
        self.last_desktop_observation = current
        self._log_action("observe", "desktop diff", "completed", str(diff.get("summary", "")))
        if diff.get("changed"):
            self._remember_observation(current, source="desktop diff")
        lines = [self.desktop_observer.summarize(current), "", str(diff.get("summary", ""))]
        return "\n".join(line for line in lines if line.strip())

    def set_observe_mode(self, enabled: bool) -> str:
        self._reload_runtime_preferences()
        self.observe_mode_enabled = enabled
        if enabled:
            observation = self.desktop_observer.observe(include_screenshot=False)
            self._remember_observation(observation, source="observe mode")
            self._log_action("observe", "observe mode", "enabled", str(observation.get("inferred_activity", "")))
            return "Luna: Pozorovani obrazovky je zapnute. Budu s nim pocitat i pri dalsich odpovedich. 👀"
        self._log_action("observe", "observe mode", "disabled", "Observe mode disabled.")
        return "Luna: Pozorovani obrazovky jsem vypnula."

    def _handle_observation_command(self, user_input: str) -> str | None:
        normalized = ascii_fold_text(" ".join(user_input.strip().lower().split()))
        screenshot_triggers = {
            "zachyt obrazovku",
            "vyfot obrazovku",
            "udelaj screenshot",
            "capture screen",
            "take a screenshot",
            "screenshot",
        }
        observe_triggers = {
            "co vidis na obrazovce",
            "co vidis na monitoru",
            "pozoruj obrazovku",
            "co mas pred sebou",
            "v jake appce jsem",
            "jaka appka je otevrena",
            "co ted delam na pc",
            "what is on the screen",
            "what do you see on screen",
            "observe desktop",
            "what app is open",
            "what am i doing on pc",
        }
        diff_triggers = {
            "co se zmenilo na obrazovce",
            "co se zmenilo na monitoru",
            "what changed on screen",
            "what changed on the screen",
        }
        enable_triggers = {
            "zapni observe mode",
            "zapni pozorovani obrazovky",
            "start observe mode",
            "enable observe mode",
        }
        disable_triggers = {
            "vypni observe mode",
            "vypni pozorovani obrazovky",
            "stop observe mode",
            "disable observe mode",
        }
        if normalized in screenshot_triggers:
            return self.observe_desktop(include_screenshot=True)
        if normalized in diff_triggers:
            return self.diff_desktop_observation(include_screenshot=False)
        if normalized in enable_triggers:
            return self.set_observe_mode(True)
        if normalized in disable_triggers:
            return self.set_observe_mode(False)
        if normalized in observe_triggers:
            return self.observe_desktop(include_screenshot=False)
        return None

    def _handle_screen_share_help_command(self, user_input: str) -> str | None:
        normalized = ascii_fold_text(" ".join(user_input.strip().lower().split()))
        if not normalized:
            return None
        share_terms = [
            "sdileni obrazovky",
            "sdilet obrazovku",
            "share screen",
            "screen share",
            "desktop share",
            "share desktop",
            "shere desktop",
            "share deskop",
            "shere deskop",
            "deskop share",
            "zivy nahled",
            "live stream pro ai",
            "live vision",
        ]
        if not any(term in normalized for term in share_terms):
            return None

        return (
            "Luna: Desktop share už nebudeme brát jako hlavní workflow. Vision teď dává větší smysl jako "
            "rozpoznávání konkrétního obrázku, dokumentu, videa nebo jednorázového screenshotu.\n\n"
            "1. Klikni na `+` vedle pole pro zprávu.\n"
            "2. Vyber `Analyze file / document`, nebo `Capture screenshot`.\n"
            "3. Pošli obrázek, PDF/dokument, video, nebo aktuální screenshot.\n"
            "4. Luna a Xeno použijí nejčerstvější vizuální kontext pro odpověď nebo agent plán.\n\n"
            "Takhle se vyhneme trvalému streamování a AI bude pracovat s přesným vstupem, který jí opravdu chceš ukázat. 👀"
        )

    def _handle_local_capability_command(self, user_input: str) -> str | None:
        normalized = ascii_fold_text(" ".join(user_input.strip().lower().split()))
        auto_mode_triggers = {
            "agent auto",
            "agent automaticky",
            "automaticky agent",
            "zapni automaticky agent",
            "zapni operator mod",
            "operator mode",
            "plne automaticky",
            "plne automaticky agent",
        }
        if normalized in auto_mode_triggers:
            summary = self.set_system_control_profile("operator")
            return "Luna: Agent je prepnuty do automatickeho operator rezimu. Bezpecne akce budu spoustet rovnou.\n" + summary

        ask_mode_triggers = {
            "agent ask",
            "agent potvrzeni",
            "vyzaduj potvrzeni",
            "zapni potvrzeni",
            "assist mode",
        }
        if normalized in ask_mode_triggers:
            summary = self.set_system_control_profile("assist")
            return "Luna: Agent je zpatky v potvrzovacim rezimu.\n" + summary

        block_mode_triggers = {
            "agent block",
            "zablokuj agenta",
            "vypni akce agenta",
            "observe mode",
        }
        if normalized in block_mode_triggers:
            summary = self.set_system_control_profile("observe")
            return "Luna: Lokalne akce agenta jsou blokovane, zustava jen pozorovani a odpovedi.\n" + summary

        trace_triggers = {
            "agent status",
            "agent trace",
            "stav agenta",
            "trace agenta",
            "jak je na tom agent",
            "co dela agent",
            "co dela agent ted",
            "ukaz agent trace",
            "ukaz stav agenta",
        }
        if normalized in trace_triggers:
            return self.format_agent_trace_status()

        run_state_triggers = {
            "agent run",
            "agent state",
            "run state",
            "stav runu",
            "stav behu",
            "stav běhu",
            "co prave dela agent",
            "co právě dělá agent",
            "kdo ted vede",
            "kdo teď vede",
        }
        if normalized in run_state_triggers:
            return self.format_agent_run_state()

        loop_triggers = {
            "agent loop",
            "spust agent loop",
            "spust agenta",
            "pust agenta",
            "autonomni loop",
            "automaticky loop",
            "run agent loop",
            "dodelat ukoly",
            "udelej dalsi kroky",
        }
        if normalized in loop_triggers:
            project = self.projects.get_current_project()
            if project is None:
                return "Luna: Nemam aktivni projekt, na kterem bych pustila agent loop."
            result = self.run_next_agent_chain(project.id, max_steps=5)
            return "Luna: " + repair_text(str(result.get("message", "Agent loop skoncil."))).strip()

        tool_triggers = {
            "agent tools",
            "tools",
            "nastroje",
            "nastroje agenta",
            "jake mas tooly",
            "jake nastroje mas",
            "ukaz tools",
            "ukaz nastroje agenta",
            "vypis tooly",
        }
        if normalized in tool_triggers:
            return self.format_agent_tools_status()

        triggers = {
            "co umis na pc",
            "co umis delat na pc",
            "co umis delat v pc",
            "co umis lokalne",
            "jake aplikace mas napojene",
            "jake appky mas napojene",
            "what can you do on this pc",
            "what local actions can you do",
            "what apps are connected",
        }
        if normalized in triggers:
            return self.describe_local_capabilities()
        return None
    def list_system_control_profiles(self) -> list[dict[str, str]]:
        return self.system_control.list_profiles()

    def get_system_control_summary(self) -> str:
        return self.system_control.profile_summary(self.user_settings.data)

    def set_system_control_profile(self, profile_key: str) -> str:
        workspace = self.system_control.apply_profile(self.user_settings.data, profile_key)
        self.user_settings.save(workspace)
        summary = self.system_control.profile_summary(workspace)
        self._log_action("system_control", f"control profile -> {workspace.system_control_profile}", "completed", summary)
        return summary
    def list_recent_actions(self, limit: int = 8) -> list[dict[str, str]]:
        return [
            {
                "timestamp": entry.timestamp,
                "category": entry.category,
                "title": entry.title,
                "status": entry.status,
                "detail": entry.detail,
            }
            for entry in self.action_log.recent(limit)
        ]

    def format_recent_actions(self, limit: int = 8) -> str:
        entries = self.list_recent_actions(limit)
        if not entries:
            return "Zatim tu nejsou zadne nedavne akce."
        lines: list[str] = []
        for entry in entries:
            lines.append(f"[{entry['timestamp']}] {entry['status'].upper()} - {entry['title']}")
            if entry["detail"]:
                lines.append(entry["detail"])
        return "\n\n".join(lines)

    def _coerce_action_result(self, raw: object, *, category: str, title: str) -> dict[str, object]:
        if isinstance(raw, dict):
            result = dict(raw)
        else:
            message = repair_text(str(raw)).strip()
            result = {
                "ok": True,
                "status": "completed",
                "message": message,
                "detail": message,
            }
        result.setdefault("ok", True)
        result.setdefault("status", "completed")
        result.setdefault("message", "Hotovo.")
        result.setdefault("detail", str(result.get("message", "")).strip())
        result.setdefault("category", category)
        result.setdefault("action_key", title)
        return result

    def _format_action_result_for_chat(self, result: dict[str, object], *, pending: bool = False) -> str:
        status = str(result.get("status", "completed")).strip().lower()
        message = repair_text(str(result.get("message", "")).strip())
        detail = repair_text(str(result.get("detail", "")).strip())

        def clean_visible_text(value: str) -> str:
            cleaned = repair_text(str(value or "")).strip()
            cleaned = re.sub(r"^(?:Luna|Agent|Xeno)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
            if self._extract_model_json_object(cleaned) is not None:
                return "Interni akcni plan jsem zachytila a predala executor vrstve."
            return cleaned

        message = clean_visible_text(message)
        detail = clean_visible_text(detail)
        if pending:
            xeno_note = repair_text(str(result.get("xeno_note", "")).strip())
            if xeno_note:
                return f"Luna: Xeno zkontroloval plan: {xeno_note} Akce je pripravena. Staci dat Accept, nebo ji zrusit pres Cancel."
            return "Luna: Akce je pripravena. Staci dat Accept, nebo ji zrusit pres Cancel."
        if status == "blocked":
            return f"Luna: Tuhle akci ted nemuzu spustit. {detail or message}".strip()
        if status == "failed":
            return f"Luna: Tohle se nepovedlo. {detail or message}".strip()
        if status == "cancelled":
            return f"Luna: Akci jsem zrusila. {detail or message}".strip()
        return f"Luna: {message}".strip()

    def _should_action_loop_verify(self, category: str) -> bool:
        return str(category or "").strip().lower() not in {"file_read", "observe", "system_control"}

    def _should_action_loop_use_vision(self, category: str) -> bool:
        return str(category or "").strip().lower() in {"app_launch", "path_open", "project_run", "system_input"}

    def _observe_for_action_loop(self, *, include_screenshot: bool = False) -> dict[str, object] | None:
        try:
            return self.desktop_observer.observe(include_screenshot=include_screenshot)
        except Exception:
            return None

    def _compact_verification_text(self, value: object, limit: int = 220) -> str:
        text = repair_text(str(value or "")).strip()
        text = " ".join(text.split())
        if len(text) > limit:
            return text[: limit - 1].rstrip() + "..."
        return text

    def _browser_target_matches_observation(
        self,
        target_domain: str,
        observation: dict[str, object],
    ) -> bool:
        normalized_domain = ascii_fold_text(str(target_domain or "")).lower().strip()
        if not normalized_domain:
            return False
        normalized_domain = normalized_domain.removeprefix("www.")
        url_hint = ascii_fold_text(str(observation.get("url_hint", "") or "")).lower().strip()
        title = ascii_fold_text(str(observation.get("active_window_title", "") or "")).lower().strip()

        domain_aliases = {
            "youtube.com": {"youtube", "youtu.be"},
            "google.com": {"google"},
            "mail.google.com": {"gmail", "google mail"},
            "github.com": {"github"},
            "chatgpt.com": {"chatgpt", "openai"},
            "reddit.com": {"reddit"},
            "discord.com": {"discord"},
            "x.com": {"x", "twitter"},
        }

        candidate_tokens = {normalized_domain}
        for domain, aliases in domain_aliases.items():
            normalized_key = domain.removeprefix("www.")
            if normalized_domain == normalized_key or normalized_domain.endswith(f".{normalized_key}"):
                candidate_tokens.update(aliases)
        return any(token and (token in url_hint or token in title) for token in candidate_tokens)

    def _verify_action_target(
        self,
        result: dict[str, object],
        after: dict[str, object],
    ) -> tuple[bool, str]:
        expected_app_key = ascii_fold_text(str(result.get("expected_app_key", "") or "")).lower().strip()
        observed_app_key = ascii_fold_text(str(after.get("app_key", "") or "")).lower().strip()
        if expected_app_key and observed_app_key != expected_app_key:
            return False, f"Aktivní aplikace po akci je `{observed_app_key or 'unknown'}`, ne očekávaný `{expected_app_key}`."

        target_domain = ascii_fold_text(str(result.get("target_domain", "") or "")).lower().strip()
        if target_domain and not self._browser_target_matches_observation(target_domain, after):
            return False, f"Nepodařilo se mi potvrdit, že je otevřený web `{target_domain}`."

        return True, ""

    def _attach_action_loop_verification(
        self,
        result: dict[str, object],
        *,
        category: str,
        title: str,
        before: dict[str, object] | None,
    ) -> dict[str, object]:
        status = str(result.get("status", "completed")).strip().lower()
        if status in {"blocked", "failed", "cancelled", "pending"} or not bool(result.get("ok", True)):
            return result
        if not self._should_action_loop_verify(category):
            return result

        if category in {"app_launch", "path_open", "project_run", "system_input"}:
            time.sleep(0.55)

        include_screenshot = self._should_action_loop_use_vision(category) and self.vision_model.is_available()
        after = self._observe_for_action_loop(include_screenshot=include_screenshot)
        if after is None:
            return result

        diff = self.desktop_observer.diff(before, after) if before else {}
        self.last_desktop_observation = after

        app_label = self._compact_verification_text(after.get("app_label") or "desktop")
        activity = self._compact_verification_text(after.get("inferred_activity") or "desktop activity")
        window_title = self._compact_verification_text(after.get("active_window_title") or "", limit=90)
        changed = bool(diff.get("changed")) if diff else True
        change_note = "zmena na plose byla detekovana" if changed else "plocha vypada stabilne"
        verification = f"Overeni: {change_note}; aktivni je {app_label} ({activity})."
        if window_title:
            verification += f" Okno: {window_title}."

        screenshot_path = str(after.get("screenshot_path", "") or "").strip()
        if screenshot_path:
            vision_analysis = self._analyze_visual_structured(
                [screenshot_path],
                (
                    "Verify the result of this desktop action for LunaAI. "
                    f"Action: {title}. Return structured JSON about the visible result."
                ),
                source="screenshot",
            )
            vision_summary = self.vision_layer.summarize(vision_analysis) if vision_analysis.get("ok") else ""
            if vision_summary:
                after["vision_analysis"] = vision_analysis
                after["vision_summary"] = vision_summary
                verification += " Vision: " + self._compact_verification_text(vision_summary, limit=260)

        target_confirmed, target_note = self._verify_action_target(result, after)
        if not target_confirmed:
            result["ok"] = False
            result["status"] = "failed"
            base_message = repair_text(str(result.get("message", "")).strip())
            result["message"] = f"Akci jsem zkusila spustit, ale výsledek jsem nepotvrdila. {target_note}".strip()
            base_detail = repair_text(str(result.get("detail", "")).strip())
            verification = f"{verification} Cílový výsledek nebyl potvrzen: {target_note}".strip()
            result["verification"] = verification
            result["detail"] = "\n\n".join(part for part in [base_detail or base_message, verification] if part).strip()
            return result

        result["verification"] = verification
        message = repair_text(str(result.get("message", "")).strip())
        detail = repair_text(str(result.get("detail", "")).strip())
        result["message"] = f"{message} {verification}".strip()
        result["detail"] = f"{detail}\n\n{verification}".strip() if detail else verification
        return result

    def _run_action_with_verification(self, category: str, title: str, callback: Callable[[], object]) -> dict[str, object]:
        before = self._observe_for_action_loop(include_screenshot=False) if self._should_action_loop_verify(category) else None
        result = self._coerce_action_result(callback(), category=category, title=title)
        return self._attach_action_loop_verification(result, category=category, title=title, before=before)

    def _action_plan_note(self, action_plan: dict[str, object] | None, limit: int = 190) -> str:
        if not action_plan:
            return ""
        note = repair_text(str(action_plan.get("reason", "")).strip())
        if len(note) > limit:
            note = note[: limit - 1].rstrip() + "…"
        return note

    def _set_action_coordination(
        self,
        *,
        category: str,
        title: str,
        action_plan: dict[str, object] | None,
        phase: str,
    ) -> None:
        xeno_note = self._action_plan_note(action_plan) or "Xeno drží kontrolu rizika a další bezpečný krok."
        luna_note = "Připravuji akci k potvrzení." if phase == "prepare" else "Provádím potvrzenou akci."
        self.last_coordination = {
            "lunaActive": True,
            "xenoActive": True,
            "tracks": [
                {
                    "speaker": "Luna",
                    "title": "Luna action",
                    "note": f"{luna_note} {self._compact_coordination_text(title, 120)}",
                },
                {
                    "speaker": "Xeno",
                    "title": "Xeno action check",
                    "note": xeno_note,
                },
            ],
        }

    def _plan_action_with_xeno(self, category: str, title: str) -> dict[str, object]:
        route = self._active_agent_route
        tool = self._tool_for_action(category, title)
        route_note = ""
        if route is not None:
            route_note = (
                f" Agent route: source={route.input_source}, scope={route.action_scope}, "
                f"risk={route.risk}, vision={'yes' if route.vision_active else 'no'}, "
                f"auto={'yes' if route.force_auto_execution else 'no'}."
            )
        tool_note = ""
        if tool is not None:
            tool_note = (
                f" Tool contract: {tool.name}, risk={tool.risk}, "
                f"confirmation={'yes' if tool.requires_confirmation else 'no'}."
            )
        simple_reasons = {
            "app_launch": "Otevření aplikace, URL nebo webového hledání je lokální akce. Spustím ji jen podle nastaveného režimu potvrzení.",
            "path_open": "Otevření cesty nemění soubory, jen zobrazí existující soubor nebo složku.",
            "file_read": "Čtení souboru nebo výpis složky nic nemění v počítači, pouze vrátí obsah nebo seznam položek.",
            "project_run": "Spuštění projektu je lokální akce a může otevřít proces nebo prohlížeč, proto respektuje potvrzení.",
            "dependency_install": "Instalace balicku meni zavislosti projektu, proto vyzaduje potvrzeni i v automatickem rezimu.",
            "system_input": "Systemovy vstup ovlada aktivni okno, proto ho v auto rezimu provadim jen jako presny, omezeny krok.",
        }
        if category in simple_reasons:
            requires_confirmation = self._action_mode() == "ask"
            if category == "system_input":
                requires_confirmation = self._action_mode() != "auto"
            if category == "dependency_install":
                requires_confirmation = True
            return {
                "status": "approved",
                "intent": category,
                "risk": "low" if category in {"path_open", "file_read"} else "medium",
                "requiresConfirmation": requires_confirmation,
                "recommendedAction": title,
                "reason": simple_reasons[category] + route_note + tool_note,
                "category": category,
                "toolName": tool.name if tool is not None else "",
                "toolRisk": tool.risk if tool is not None else "",
            }
        try:
            action_plan = self.xeno.plan_action(
                category=category,
                title=title,
                user_input=route.user_input if route is not None else "",
                project_context=self._project_context(),
                desktop_context=self._observer_context(refresh=False),
            )
        except Exception as error:
            action_plan = {
                "status": "approved",
                "intent": category,
                "risk": "medium",
                "requiresConfirmation": True,
                "recommendedAction": title,
                "reason": f"Xeno kontrola spadla, Luna proto drží konzervativní režim potvrzení. Detail: {error}",
                "category": category,
            }
        if tool is not None:
            action_plan["toolName"] = tool.name
            action_plan["toolRisk"] = tool.risk
            action_plan["toolRequiresConfirmation"] = tool.requires_confirmation
            existing_reason = str(action_plan.get("reason", "") or "")
            if tool_note and tool.name not in existing_reason:
                action_plan["reason"] = (existing_reason + tool_note).strip()
        return action_plan

    def _project_memory_sections(self, project: object) -> dict[str, list[str]]:
        buckets = {"execution": [], "handoff": [], "focus": [], "other": []}
        for item in getattr(project, "memory_entries", [])[:16]:
            normalized = item.lower()
            if normalized.startswith(("agent action:", "agent failed:", "task updated:")):
                buckets["execution"].append(item)
            elif normalized.startswith(("agent handoff:", "agent next step:", "xeno model guidance:", "xeno refreshed")):
                buckets["handoff"].append(item)
            elif normalized.startswith(("chat focus:", "luna direction:")):
                buckets["focus"].append(item)
            else:
                buckets["other"].append(item)
        return buckets

    def _guarded_action(self, category: str, title: str, callback: Callable[[], object]) -> str:
        if self.pending_action is not None and self.pending_action[1] != title:
            current_title = self.pending_action[1]
            return f"Luna: Nejdriv prosim vyrid cekajici akci `{current_title}`. Pak muzu pripravit dalsi."
        action_plan = self._plan_action_with_xeno(category, title)
        tool_name = str(action_plan.get("toolName", "") or "")
        self.agent_run_state.update(
            status="planned",
            owner="Xeno" if bool(action_plan.get("xeno_consulted", True)) else "Luna",
            action_title=title,
            tool_name=tool_name,
            requires_confirmation=bool(action_plan.get("requiresConfirmation", False)),
            note=self._action_plan_note(action_plan),
        )
        self._set_action_coordination(category=category, title=title, action_plan=action_plan, phase="prepare")
        if str(action_plan.get("status", "")).strip().lower() == "blocked":
            result = self._coerce_action_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "message": "Xeno tuhle akci zastavil.",
                    "detail": self._action_plan_note(action_plan) or "Xeno marked this action as blocked.",
                },
                category=category,
                title=title,
            )
            self._log_action(category, title, "blocked", str(result.get("detail", "")))
            self.agent_run_state.update(status="blocked", final_message=str(result.get("detail", "")))
            self._trace_agent(
                phase="xeno_check",
                status="blocked",
                detail=str(result.get("detail", "")),
                metadata={"category": category, "title": title, "tool": tool_name},
            )
            return self._format_action_result_for_chat(result)
        if not self._is_action_allowed(category):
            result = self._coerce_action_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "message": "Tuhle akci ted blokuji aktualni opravneni.",
                    "detail": f"{title} is blocked by the current agent permissions.",
                },
                category=category,
                title=title,
            )
            self._log_action(category, title, "blocked", str(result.get("detail", "")))
            self.agent_run_state.update(status="blocked", final_message=str(result.get("detail", "")))
            self._trace_agent(
                phase="action_policy",
                status="blocked",
                detail=str(result.get("detail", "")),
                metadata={"category": category, "title": title, "tool": tool_name},
            )
            return self._format_action_result_for_chat(result)
        mode = self._action_mode()
        force_confirmation = (category in {"system_input"} and mode != "auto") or category in {"dependency_install"}
        if mode == "block":
            result = self._coerce_action_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "message": "Akce je blokovana, protoze system je v block rezimu.",
                    "detail": f"{title} is blocked because agent execution mode is set to block.",
                },
                category=category,
                title=title,
            )
            self._log_action(category, title, "blocked", str(result.get("detail", "")))
            self.agent_run_state.update(status="blocked", final_message=str(result.get("detail", "")))
            self._trace_agent(
                phase="action_policy",
                status="blocked",
                detail=str(result.get("detail", "")),
                metadata={"category": category, "title": title, "tool": tool_name},
            )
            return self._format_action_result_for_chat(result)
        if mode == "ask" or force_confirmation:
            self.pending_action = (category, title, callback)
            self.pending_action_plan = action_plan
            self._log_action(category, title, "pending", f"Pending approval for {title}.")
            self.agent_run_state.update(status="awaiting_confirmation", requires_confirmation=True)
            self._trace_agent(
                phase="action_plan",
                status="pending",
                detail=self._action_plan_note(action_plan) or f"Pending approval for {title}.",
                metadata={"category": category, "title": title, "mode": mode, "tool": tool_name},
            )
            return self._format_action_result_for_chat(
                {
                    "status": "pending",
                    "message": "pending",
                    "xeno_note": self._action_plan_note(action_plan),
                },
                pending=True,
            )
        try:
            self.agent_run_state.update(status="executing", requires_confirmation=False)
            self._set_action_coordination(category=category, title=title, action_plan=action_plan, phase="execute")
            result = self._run_action_with_verification(category, title, callback)
        except OSError as error:
            result = self._coerce_action_result(
                {
                    "ok": False,
                    "status": "failed",
                    "message": "Akce selhala.",
                    "detail": f"{title} failed: {error}",
                },
                category=category,
                title=title,
            )
            self._log_action(category, title, "failed", str(result.get("detail", "")))
            self.agent_run_state.update(status="failed", final_message=str(result.get("detail", "")))
            self._trace_agent(
                phase="action_execute",
                status="failed",
                detail=str(result.get("detail", "")),
                metadata={"category": category, "title": title, "tool": tool_name},
            )
            return self._format_action_result_for_chat(result)
        self._log_action(category, title, str(result.get("status", "completed")), str(result.get("detail", result.get("message", ""))))
        self.agent_run_state.update(
            status=str(result.get("status", "completed")),
            final_message=str(result.get("verification", result.get("detail", result.get("message", "")))),
        )
        self._trace_agent(
            phase="action_execute",
            status=str(result.get("status", "completed")),
            detail=str(result.get("verification", result.get("detail", result.get("message", "")))),
            metadata={"category": category, "title": title, "tool": tool_name},
        )
        return self._format_action_result_for_chat(result)

    def has_pending_action(self) -> bool:
        return self.pending_action is not None

    def get_pending_action_title(self) -> str:
        if self.pending_action is None:
            return ""
        return self.pending_action[1]

    def confirm_pending_action(self) -> str:
        return self.chat("potvrd akci")

    def cancel_pending_action(self) -> str:
        return self.chat("zrus akci")

    def _handle_pending_action_command(self, user_input: str) -> str | None:
        normalized = " ".join(user_input.strip().lower().split())
        if normalized not in {"potvrd akci", "confirm action", "zrus akci", "cancel action"}:
            return None
        if self.pending_action is None:
            return "Luna: Ted tu nemam zadnou cekajici akci."
        category, title, callback = self.pending_action
        action_plan = self.pending_action_plan
        tool_name = str(action_plan.get("toolName", "") or "") if action_plan is not None else ""
        self.pending_action = None
        self.pending_action_plan = None
        if normalized in {"zrus akci", "cancel action"}:
            self._set_action_coordination(category=category, title=title, action_plan=action_plan, phase="prepare")
            result = self._coerce_action_result(
                {
                    "ok": False,
                    "status": "cancelled",
                    "message": "Akci jsem zrusila.",
                    "detail": f"Cancelled {title}.",
                },
                category=category,
                title=title,
            )
            self._log_action(category, title, "cancelled", str(result.get("detail", "")))
            self.agent_run_state.update(status="cancelled", final_message=str(result.get("detail", "")))
            self._trace_agent(
                phase="action_execute",
                status="cancelled",
                detail=str(result.get("detail", "")),
                metadata={"category": category, "title": title, "tool": tool_name},
            )
            return self._format_action_result_for_chat(result)
        try:
            self.agent_run_state.update(
                status="executing",
                action_title=title,
                tool_name=tool_name,
                requires_confirmation=False,
            )
            self._set_action_coordination(category=category, title=title, action_plan=action_plan, phase="execute")
            result = self._run_action_with_verification(category, title, callback)
        except OSError as error:
            result = self._coerce_action_result(
                {
                    "ok": False,
                    "status": "failed",
                    "message": "Akce se nepovedla.",
                    "detail": f"{title} failed: {error}",
                },
                category=category,
                title=title,
            )
            self._log_action(category, title, "failed", str(result.get("detail", "")))
            self.agent_run_state.update(status="failed", final_message=str(result.get("detail", "")))
            self._trace_agent(
                phase="action_execute",
                status="failed",
                detail=str(result.get("detail", "")),
                metadata={"category": category, "title": title, "tool": tool_name},
            )
            return self._format_action_result_for_chat(result)
        self._log_action(category, title, str(result.get("status", "completed")), str(result.get("detail", result.get("message", ""))))
        self.agent_run_state.update(
            status=str(result.get("status", "completed")),
            final_message=str(result.get("verification", result.get("detail", result.get("message", "")))),
        )
        self._trace_agent(
            phase="action_execute",
            status=str(result.get("status", "completed")),
            detail=str(result.get("verification", result.get("detail", result.get("message", "")))),
            metadata={"category": category, "title": title, "tool": tool_name},
        )
        return self._format_action_result_for_chat(result)

    def _resolve_local_target(self, raw_target: str) -> Path | None:
        target_text = raw_target.strip().strip('"').strip("'")
        if not target_text:
            return None
        candidate = Path(target_text).expanduser()
        if candidate.exists():
            return candidate
        workspace_candidate = (Path.cwd() / target_text).resolve()
        if workspace_candidate.exists():
            return workspace_candidate
        return None

    def _resolve_known_user_folder(self, raw_target: str) -> Path | None:
        cleaned = ascii_fold_text(raw_target).lower().strip(" .,:;\"'")
        cleaned = re.sub(r"^(?:moje|moji|muj|my|the)\s+", "", cleaned)
        cleaned = re.sub(r"^(?:slozka|folder|adresar)\s+", "", cleaned).strip()
        home = Path.home()
        known_folders: dict[str, Path] = {
            "home": home,
            "profil": home,
            "uzivatel": home,
            "user": home,
            "plocha": home / "Desktop",
            "plochu": home / "Desktop",
            "desktop": home / "Desktop",
            "downloads": home / "Downloads",
            "stazene": home / "Downloads",
            "stazeni": home / "Downloads",
            "stazene soubory": home / "Downloads",
            "dokumenty": home / "Documents",
            "dokumentu": home / "Documents",
            "documents": home / "Documents",
            "obrazky": home / "Pictures",
            "obrazku": home / "Pictures",
            "pictures": home / "Pictures",
            "videa": home / "Videos",
            "videi": home / "Videos",
            "videos": home / "Videos",
            "hudba": home / "Music",
            "hudbu": home / "Music",
            "music": home / "Music",
        }
        target = known_folders.get(cleaned)
        if target is not None and target.exists():
            return target
        return None

    def _resolve_pc_target(self, raw_target: str, *, prefer_directory: bool | None = None) -> Path | None:
        target_text = repair_text(raw_target).strip().strip('"').strip("'")
        target_text = re.sub(r"\s+(?:ve|v)\s+(?:vscode|vs code)$", "", target_text, flags=re.IGNORECASE).strip()
        if not target_text:
            return self._default_action_root() if prefer_directory is not False else None

        folded = ascii_fold_text(target_text).lower().strip(" .,:;")
        if folded in {"tady", "zde", "projekt", "workspace", "root", "koren", "."}:
            return self._default_action_root() if prefer_directory is not False else None

        known_folder = self._resolve_known_user_folder(target_text)
        if known_folder is not None:
            if prefer_directory is False and not known_folder.is_file():
                return None
            return known_folder

        local_target = self._resolve_local_target(target_text)
        if local_target is not None:
            if prefer_directory is True and not local_target.is_dir():
                return None
            if prefer_directory is False and not local_target.is_file():
                return None
            return local_target

        named_target = self._find_named_target(target_text, prefer_directory=prefer_directory)
        if named_target is not None:
            return named_target
        return self._find_recent_workspace_target(target_text, prefer_directory=prefer_directory)

    def _default_action_root(self) -> Path:
        current_project = self.projects.get_current_project()
        if current_project is not None:
            return self.desktop_actions.ensure_project_workspace(current_project.name)
        return Path.cwd()

    def _resolve_creation_target(self, raw_target: str) -> Path:
        target_text = raw_target.strip().strip('"').strip("'")
        if not target_text:
            return self._default_action_root()
        candidate = Path(target_text).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self._default_action_root() / candidate).resolve()

    def _parse_folder_names(self, raw_targets: str) -> list[str]:
        cleaned = raw_targets.strip().strip('"').strip("'")
        if not cleaned:
            return []
        if re.fullmatch(r'(?:ve|v)\s+(?:vscode|vs code|projektu|projectu|workspace)', cleaned, flags=re.IGNORECASE):
            return []
        cleaned = re.sub(r'(?:^|\s+)(?:ve|v)\s+(?:vscode|vs code|projektu|projectu|workspace)\s*$', '', cleaned, flags=re.IGNORECASE).strip()
        if not cleaned:
            return []
        parts = [part.strip().strip('"').strip("'") for part in re.split(r",|;", cleaned) if part.strip()]
        if len(parts) == 1 and "/" not in parts[0] and "\\" not in parts[0] and " " in parts[0]:
            parts = [part.strip() for part in parts[0].split() if part.strip()]
        return [part for part in parts if part and part not in {".", ".."}]

    def _extract_email_details(self, raw_input: str) -> dict[str, str]:
        recipient = ""
        email_match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw_input)
        if email_match:
            recipient = email_match.group(0).strip()

        subject = ""
        subject_match = re.search(
            r"(?:predmet|p\?edmet|subject)\s*[:\-]?\s*(.+?)(?=\s+(?:text|body|zprava|message)\b|$)",
            ascii_fold_text(raw_input),
            flags=re.IGNORECASE,
        )
        if subject_match:
            subject = subject_match.group(1).strip(" .,:;-")

        body = ""
        body_match = re.search(
            r"(?:text|body|zprava|message)\s*[:\-]?\s*(.+)$",
            raw_input,
            flags=re.IGNORECASE,
        )
        if body_match:
            body = body_match.group(1).strip()
        if not body:
            soft_body_match = re.search(r"(?:ze|že)\s+(.+)$", raw_input, flags=re.IGNORECASE)
            if soft_body_match:
                body = soft_body_match.group(1).strip()

        return {
            "recipient": recipient,
            "subject": subject,
            "body": body,
        }

    def _search_roots(self) -> list[Path]:
        roots: list[Path] = []
        current_project = self.projects.get_current_project()
        if current_project is not None:
            roots.append(self.desktop_actions.ensure_project_workspace(current_project.name))
        cwd = Path.cwd()
        if cwd not in roots:
            roots.append(cwd)
        return roots

    def _pc_file_search_roots(self) -> list[Path]:
        roots = [*self._search_roots()]
        home = Path.home()
        for candidate in [
            home / "Desktop",
            home / "Desktop" / "Aplikace",
            home / "Documents",
            home / "Downloads",
            home / "Pictures",
            home / "Videos",
            home / "Music",
            self.desktop_actions.workspace_root,
        ]:
            if candidate.exists() and candidate not in roots:
                roots.append(candidate)
        return roots

    def _pc_app_search_roots(self) -> list[Path]:
        roots = [*self._pc_file_search_roots()]
        home = Path.home()
        for env_name, suffix in [
            ("PROGRAMFILES", ""),
            ("PROGRAMFILES(X86)", ""),
            ("LOCALAPPDATA", "Programs"),
            ("APPDATA", "Microsoft/Windows/Start Menu/Programs"),
            ("PROGRAMDATA", "Microsoft/Windows/Start Menu/Programs"),
        ]:
            base = str(os.environ.get(env_name, "") or "").strip()
            if not base:
                continue
            candidate = Path(base) / suffix if suffix else Path(base)
            if candidate.exists() and candidate not in roots:
                roots.append(candidate)
        desktop_apps = home / "Desktop" / "Aplikace"
        if desktop_apps.exists() and desktop_apps not in roots:
            roots.append(desktop_apps)
        return roots

    def _find_named_target(self, target_name: str, *, prefer_directory: bool | None = None) -> Path | None:
        clean_name = target_name.strip().strip('"').strip("'")
        if not clean_name:
            return None
        lower_name = clean_name.lower()
        for root in self._search_roots():
            if not root.exists():
                continue
            try:
                for path in root.rglob("*"):
                    if path.name.lower() != lower_name:
                        continue
                    if prefer_directory is True and not path.is_dir():
                        continue
                    if prefer_directory is False and not path.is_file():
                        continue
                    return path
            except OSError:
                continue
        return None

    def _mentions_vscode(self, text: str) -> bool:
        lowered = ascii_fold_text(text).lower()
        return any(
            marker in lowered
            for marker in [
                "vscode",
                "vs code",
                "vscodu",
                "vs codu",
                "visual studio code",
                "code.exe",
            ]
        )

    def _known_app_key(self, text: str) -> str:
        lowered = ascii_fold_text(str(text or "")).lower().strip()
        app_aliases = {
            "vscode": ["vscode", "vs code", "vscodu", "vs codu", "visual studio code", "code.exe"],
            "chrome": ["chrome", "chrom", "google chrome", "prohlizec", "browser"],
            "blender": ["blender"],
            "unreal": ["unreal", "unreal engine", "unreal engine 5", "ue5"],
            "unity": ["unity"],
            "photoshop": ["photoshop"],
            "davinci": ["davinci", "davinci resolve"],
            "premiere": ["premiere", "premiere pro"],
            "after_effects": ["after effects", "aftereffects"],
            "figma": ["figma"],
            "fl_studio": ["fl studio"],
            "substance": ["substance", "substance painter", "substance 3d painter"],
        }
        for app_key, aliases in app_aliases.items():
            if lowered in aliases or any(alias in lowered for alias in aliases):
                return app_key
        try:
            item = find_registered_app(lowered)
            return item['title'] if item else ""
        except (OSError, ValueError, RuntimeError):
            return ""

    def _find_recent_workspace_target(self, target_name: str, *, prefer_directory: bool | None = None) -> Path | None:
        clean_name = target_name.strip().strip('"').strip("'").lower()
        if not clean_name:
            return None

        workspace_root = self.desktop_actions.workspace_root
        if not workspace_root.exists():
            return None

        candidates: list[Path] = []
        try:
            for path in workspace_root.rglob("*"):
                if path.name.lower() != clean_name:
                    continue
                if prefer_directory is True and not path.is_dir():
                    continue
                if prefer_directory is False and not path.is_file():
                    continue
                candidates.append(path)
        except OSError:
            return None

        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        return candidates[0]

    def _split_action_chain(self, user_input: str) -> list[str]:
        normalized = ascii_fold_text(" ".join(user_input.strip().split()))

        targeted_patterns = [
            r'^(otevri(?:t)?|otev\?i(?:t)?|open|spust|spustit|launch) (.+?) a (vytvor|vytvo\?|udelej|ud\?lej|create|make) (.+)$',
        ]
        for pattern in targeted_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            first_verb = str(match.group(1)).strip()
            first_target = str(match.group(2)).strip()
            second_verb = str(match.group(3)).strip()
            second_target = str(match.group(4)).strip()
            first_part = f"{first_verb} {first_target}".strip(' ,.')
            second_part = f"{second_verb} {second_target}".strip(' ,.')
            if first_part and second_part:
                return [first_part, second_part]

        separators = [
            r"\s+a pak\s+",
            r"\s+a\s+",
            r"\s+potom\s+",
            r"\s+and then\s+",
            r"\s+then\s+",
        ]
        for separator in separators:
            if re.search(separator, normalized, flags=re.IGNORECASE):
                parts = [part.strip(" ,.") for part in re.split(separator, normalized, flags=re.IGNORECASE) if part.strip(" ,.")]
                if len(parts) > 1 and all(self._looks_like_action_phrase(part) for part in parts):
                    return parts
        return [normalized]

    def _looks_like_action_phrase(self, text: str) -> bool:
        lowered = ascii_fold_text(str(text or "")).lower().strip()
        if not lowered:
            return False
        action_markers = (
            "otevri",
            "otevrit",
            "open",
            "spust",
            "spustit",
            "zapni",
            "launch",
            "start",
            "jdi na",
            "go to",
            "bez na",
            "naviguj na",
            "najdi",
            "hledej",
            "find",
            "kde je",
            "vyhledej",
            "search",
            "google",
            "dej",
            "hod",
            "klikni",
            "click",
            "stiskni",
            "press",
            "napis",
            "type",
        )
        return any(lowered.startswith(marker) for marker in action_markers)

    def _known_web_alias_url(self, value: str) -> str | None:
        alias = ascii_fold_text(str(value or "")).lower().strip().strip("/").strip()
        alias_map = {
            "youtube": "https://www.youtube.com",
            "yt": "https://www.youtube.com",
            "google": "https://www.google.com",
            "gmail": "https://mail.google.com",
            "outlook": "https://outlook.live.com/mail",
            "github": "https://github.com",
            "reddit": "https://www.reddit.com",
            "discord": "https://discord.com/app",
            "chatgpt": "https://chatgpt.com",
            "openai": "https://openai.com",
            "x": "https://x.com",
            "twitter": "https://x.com",
            "facebook": "https://www.facebook.com",
            "instagram": "https://www.instagram.com",
            "twitch": "https://www.twitch.tv",
            "netflix": "https://www.netflix.com",
            "unreal": "https://www.unrealengine.com",
            "unreal engine": "https://www.unrealengine.com",
            "ue5": "https://www.unrealengine.com",
            "epic games": "https://www.epicgames.com",
            "blender": "https://www.blender.org",
            "nvidia": "https://www.nvidia.com",
            "nvidia build": "https://build.nvidia.com",
            "nvidia aiq": "https://build.nvidia.com/nvidia/aiq",
            "langchain": "https://docs.langchain.com",
            "npm": "https://www.npmjs.com",
            "react": "https://react.dev",
            "vite": "https://vite.dev",
            "electron": "https://www.electronjs.org",
            "python": "https://www.python.org",
        }
        return alias_map.get(alias)

    def _clean_search_query(self, value: str) -> str:
        cleaned = repair_text(str(value or "")).strip().strip('"').strip("'")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;!?")
        cleaned = re.sub(r"^(?:mi\s+)?(?:odkaz|link|url)\s+(?:na|to)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:mi\s+)?(?:stranku|stranka|web|website)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:mi\s+)?(?:aplikaci|program|app)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+(?:prosim|please)$", "", cleaned, flags=re.IGNORECASE).strip(" .,:;!?")
        return cleaned

    def _should_skip_reopening_active_app(self, user_input: str, app_key: str) -> bool:
        normalized_input = ascii_fold_text(repair_text(str(user_input or ""))).lower().strip()
        if not normalized_input or not app_key:
            return False

        open_markers = (
            "otevri",
            "otevrit",
            "open",
            "spust",
            "spustit",
            "zapni",
            "launch",
            "start",
        )
        if any(marker in normalized_input for marker in open_markers):
            return False

        creative_markers = (
            "udelej",
            "vytvor",
            "create",
            "make",
            "build",
            "model",
            "objekt",
            "mesh",
            "scenu",
            "scene",
            "asset",
        )
        if not any(marker in normalized_input for marker in creative_markers):
            return False

        observation = self.last_desktop_observation or {}
        observed_app_key = ascii_fold_text(str(observation.get("app_key", "") or "")).lower().strip()
        return observed_app_key == app_key

    def _is_blender_context_active(self) -> bool:
        observation = self.last_desktop_observation or {}
        observed_app_key = ascii_fold_text(str(observation.get("app_key", "") or "")).lower().strip()
        title = ascii_fold_text(str(observation.get("active_window_title", "") or "")).lower().strip()
        activity = ascii_fold_text(str(observation.get("inferred_activity", "") or "")).lower().strip()
        context = " ".join([title, activity, self._project_context()]).lower()
        return observed_app_key == "blender" or "blender" in context or ".blend" in context

    def _looks_like_blender_scene_request(self, user_input: str) -> bool:
        normalized = ascii_fold_text(repair_text(str(user_input or ""))).lower().strip()
        if not normalized:
            return False

        creation_markers = (
            "vytvor",
            "vytvo",
            "vytvoril",
            "vytvorila",
            "udelej",
            "udělej",
            "udelal",
            "udělal",
            "udelas",
            "uděláš",
            "udelat",
            "udělat",
            "pridej",
            "přidej",
            "dej tam",
            "postav",
            "make",
            "create",
            "add",
            "build",
        )
        blender_markers = (
            "blender",
            "3d",
            "model",
            "scena",
            "scene",
            "asset",
            "mesh",
            "objekt",
        )
        object_markers = (
            "auto",
            "car",
            "vehicle",
            "vozidlo",
            "mercedes",
            "benz",
            "amg",
            "c63",
            "raket",
            "rocket",
            "planet",
            "planeta",
            "mistnost",
            "místnost",
            "room",
            "studio",
        )
        if any(marker in normalized for marker in creation_markers) and any(marker in normalized for marker in blender_markers):
            return True
        if self._is_blender_context_active() and any(marker in normalized for marker in creation_markers) and any(marker in normalized for marker in object_markers):
            return True
        return False

    def _extract_model_json_object(self, text: str) -> dict[str, object] | None:
        cleaned = repair_text(str(text or "")).strip()
        if not cleaned:
            return None

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            cleaned = fenced.group(1).strip()
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            cleaned = cleaned[start : end + 1]

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _plan_agent_action_with_model(self, user_input: str) -> dict[str, object] | None:
        cleaned_input = repair_text(str(user_input or "")).strip()
        if not cleaned_input:
            return None

        route = self._active_agent_route
        route_context = route.summary if route is not None else ""
        project_context = self._project_context()
        desktop_context = self._observer_context(refresh=False)
        tools = self.tool_registry.summary_for_prompt()
        alias_lines = "\n".join(
            [
                "- youtube -> https://www.youtube.com",
                "- google -> https://www.google.com",
                "- gmail -> https://mail.google.com",
                "- unreal engine -> https://www.unrealengine.com",
                "- blender -> https://www.blender.org",
                "- github -> https://github.com",
                "- instagram -> https://www.instagram.com",
            ]
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are LunaAI's local agent planner. "
                    "Your only job is to convert the user's request into ONE safe structured tool call. "
                    "Return JSON only, no markdown and no explanation. "
                    "Never claim that anything was executed. "
                    "If the user asks for multiple browser steps like 'open chrome and put youtube', choose open_url with prefer_chrome=true. "
                    "If the request is destructive, unsafe, vague, or needs unsupported automation, return tool='none'. "
                    "Allowed tools: open_url, open_app, create_blender_scene, search_web, find_app_path, find_path, read_file, list_folder, run_command, get_system_info, none. "
                    "If the user asks to make a Blender model, Blender scene, or 3D asset, choose create_blender_scene with args.prompt. "
                    "If Blender is the active context and the user asks to add or make an object, choose create_blender_scene. "
                    "Do not choose search_web for Blender object creation unless the user explicitly asks to search the web or download an asset. "
                    "Use this JSON shape exactly: "
                    "{\"tool\":\"open_url\",\"args\":{\"url\":\"https://www.youtube.com\",\"prefer_chrome\":true},\"category\":\"app_launch\",\"requiresConfirmation\":false,\"reason\":\"short\"}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request: {cleaned_input}\n\n"
                    f"{route_context}\n\n"
                    f"{tools}\n\n"
                    "Known web aliases:\n"
                    f"{alias_lines}\n\n"
                    f"Project context:\n{project_context or 'none'}\n\n"
                    f"Desktop context:\n{desktop_context or 'none'}"
                ),
            },
        ]

        try:
            raw_plan = self._support_generate(messages)
        except Exception as error:
            self._trace_agent(
                phase="agent_model_plan",
                status="failed",
                detail=f"Model planner failed: {error}",
                metadata={"user_input": cleaned_input[:180]},
            )
            return None

        plan = self._extract_model_json_object(raw_plan)
        if plan is None:
            self._trace_agent(
                phase="agent_model_plan",
                status="fallback",
                detail="Model did not return valid JSON action plan.",
                metadata={"raw": repair_text(str(raw_plan or ""))[:400]},
            )
            return None

        tool = ascii_fold_text(str(plan.get("tool", "") or plan.get("action", ""))).lower().strip()
        allowed_tools = {
            "open_url",
            "open_app",
            "create_blender_scene",
            "search_web",
            "find_app_path",
            "find_path",
            "read_file",
            "list_folder",
            "run_command",
            "get_system_info",
            "none",
        }
        if tool not in allowed_tools or tool == "none":
            return None
        plan["tool"] = tool
        self._trace_agent(
            phase="agent_model_plan",
            status="selected",
            detail=str(plan.get("reason", "") or f"Model selected {tool}."),
            metadata={"tool": tool, "args": plan.get("args", {})},
        )
        return plan

    def _execute_model_agent_action(self, user_input: str, plan: dict[str, object]) -> str | None:
        tool = ascii_fold_text(str(plan.get("tool", ""))).lower().strip()
        raw_args = plan.get("args", plan.get("parameters", {}))
        args: dict[str, object] = {str(key): value for key, value in raw_args.items()} if isinstance(raw_args, dict) else {}
        normalized_input = ascii_fold_text(str(user_input or "")).lower()

        if tool == "open_url":
            raw_target = str(args.get("url") or args.get("target") or "").strip()
            if not raw_target:
                return None
            raw_url = self._known_web_alias_url(raw_target) or raw_target
            prefer_chrome = bool(args.get("prefer_chrome")) or "chrome" in normalized_input or "chrom" in normalized_input
            return self._guarded_action(
                "app_launch",
                f"model open url {raw_url}",
                lambda: self.desktop_actions.open_url(raw_url, prefer_chrome=prefer_chrome),
            )

        if tool == "search_web":
            query = self._clean_search_query(str(args.get("query") or args.get("target") or ""))
            if not query:
                return None
            if self._looks_like_blender_scene_request(user_input) or (
                self._is_blender_context_active()
                and any(token in ascii_fold_text(query).lower() for token in ["3d", "model", "mercedes", "amg", "c63", "car", "auto"])
            ):
                workspace = self._default_action_root()
                return self._guarded_action(
                    "file_change",
                    "model add object to Blender scene",
                    lambda: self.desktop_actions.create_blender_scene(workspace, user_input, self.user_settings.data),
                )
            prefer_chrome = bool(args.get("prefer_chrome")) or "chrome" in normalized_input or "chrom" in normalized_input
            return self._guarded_action(
                "app_launch",
                f"model search web for {query}",
                lambda: self.desktop_actions.search_web(query, prefer_chrome=prefer_chrome),
            )

        if tool == "open_app":
            app_key = self._known_app_key(str(args.get("app") or args.get("target") or user_input))
            if not app_key:
                return None
            if self._should_skip_reopening_active_app(user_input, app_key):
                self._trace_agent(
                    phase="agent_model_execute",
                    status="skipped",
                    detail=f"Skipped reopening already active app: {app_key}",
                    metadata={"tool": tool, "app_key": app_key},
                )
                return None
            if app_key == "chrome":
                return self._guarded_action(
                    "app_launch",
                    "model open Chrome",
                    lambda: self.desktop_actions.open_browser(prefer_chrome=True),
                )

            current_project = self.projects.get_current_project()
            project_name = "" if app_key == "vscode" else (current_project.name if current_project is not None else "")

            def launch_app() -> str:
                result = self.open_connected_app(app_key, project_name, log_result=False)
                message = str(result.get("message", "")).strip()
                if result.get("ok"):
                    return message
                raise OSError(message or "Aplikaci se nepodarilo otevrit.")

            return self._guarded_action("app_launch", f"model open {app_key}", launch_app)

        if tool == "create_blender_scene":
            prompt = repair_text(str(args.get("prompt") or args.get("description") or args.get("target") or user_input)).strip()
            if not prompt:
                return None
            workspace = self._default_action_root()
            return self._guarded_action(
                "file_change",
                "model create Blender scene",
                lambda: self.desktop_actions.create_blender_scene(workspace, prompt, self.user_settings.data),
            )

        if tool == "find_app_path":
            app_key = self._known_app_key(str(args.get("app") or args.get("target") or user_input))
            if not app_key:
                return None
            return self._guarded_action(
                "file_read",
                f"model find app path {app_key}",
                lambda: self.desktop_actions.describe_app_path(app_key, self.user_settings.data),
            )

        if tool == "get_system_info":
            return self._guarded_action("file_read", "model get system info", lambda: self.desktop_actions.get_system_info())

        if tool == "find_path":
            query = self._clean_search_query(str(args.get("query") or args.get("target") or ""))
            if not query:
                return None
            prefer_directory_raw = args.get("prefer_directory")
            prefer_directory = prefer_directory_raw if isinstance(prefer_directory_raw, bool) else None
            return self._guarded_action(
                "file_read",
                f"model find {query}",
                lambda: self.desktop_actions.find_paths(
                    self._pc_file_search_roots(),
                    query,
                    prefer_directory=prefer_directory,
                ),
            )

        if tool in {"read_file", "list_folder"}:
            raw_path = str(args.get("path") or args.get("target") or "").strip()
            if not raw_path:
                return None
            target = self._resolve_pc_target(raw_path, prefer_directory=(tool == "list_folder"))
            if target is None:
                return None
            if tool == "read_file":
                return self._guarded_action(
                    "file_read",
                    f"model read file {target}",
                    lambda: self.desktop_actions.read_text_file(target),
                )
            return self._guarded_action(
                "file_read",
                f"model list folder {target}",
                lambda: self.desktop_actions.list_folder(target),
            )

        if tool == "run_command":
            command_text = str(args.get("command") or "").strip()
            if not command_text:
                return None
            category = "dependency_install" if command_text.lower().startswith(("npm install", "npm i")) else "project_run"
            workspace = self._default_action_root()
            return self._guarded_action(
                category,
                f"model run command {command_text}",
                lambda: self.desktop_actions.run_safe_command(command_text, workspace),
            )

        return None

    def _try_model_agent_action(self, user_input: str) -> str | None:
        plan = self._plan_agent_action_with_model(user_input)
        if plan is None:
            return None
        try:
            return self._execute_model_agent_action(user_input, plan)
        except OSError as error:
            self._trace_agent(
                phase="agent_model_execute",
                status="failed",
                detail=str(error),
                metadata={"tool": plan.get("tool", "")},
            )
            return None

    def _try_structured_action_response(self, user_input: str, response: str) -> str | None:
        plan = self._extract_model_json_object(response)
        if plan is None:
            return None
        action_name = str(plan.get("tool", "") or plan.get("action", "")).strip()
        if not action_name:
            return None
        plan["tool"] = action_name
        if "args" not in plan and "parameters" in plan:
            plan["args"] = plan.get("parameters", {})
        try:
            return self._execute_model_agent_action(user_input, plan)
        except OSError as error:
            self._trace_agent(
                phase="agent_structured_response",
                status="failed",
                detail=str(error),
                metadata={"tool": action_name},
            )
            return None

    def _chain_action_category(self, parts: list[str]) -> str:
        lowered = " ".join(parts).lower()
        if any(token in lowered for token in ["vytvor", "udelej", "create", "make", "prepis", "rewrite", "overwrite", "append", "pridej do"]):
            return "file_change"
        if any(token in lowered for token in ["precti", "read file", "vypis slozku", "vypis folder", "list folder", "obsah slozky", "najdi soubor", "najdi slozku", "find file", "find folder"]):
            return "file_read"
        if any(token in lowered for token in ["stiskni", "zmackni", "press ", "klaves", "shortcut", "klikni", "click", "napis text", "type text", "system input"]):
            return "system_input"
        if any(token in lowered for token in ["run command", "spust prikaz", "npm start", "npm run", "npm install", "python main.py", "python src/main.py", "python -m pytest", "pytest", "get system info", "info o systemu"]):
            return "project_run"
        if any(token in lowered for token in ["vscode", "vs code", "blender", "unreal", "unity", "photoshop", "davinci", "premiere", "after effects", "figma", "fl studio", "substance", "chrome", "chrom", "browser", "prohlizec", "http://", "https://", "localhost", "vyhledej", "search", "google", "dej", "hod"]):
            return "app_launch"
        return "path_open"

    def _execute_chained_action_part(self, user_input: str) -> str | None:
        original_mode = self.user_settings.data.agent_execution_mode
        self.user_settings.data.agent_execution_mode = "auto"
        try:
            result = self._try_local_path_action(user_input)
            if result is None:
                result = self._try_local_app_action(user_input)
        finally:
            self.user_settings.data.agent_execution_mode = original_mode

        if result is None:
            return None

        cleaned = result.removeprefix("Luna: ").strip()
        if not cleaned:
            return None
        if any(token in cleaned.lower() for token in ["blocked", "nemohla", "nenasla", "chybi", "failed"]):
            raise OSError(cleaned)
        return cleaned

    def _try_local_action(self, user_input: str) -> str | None:
        if self._looks_like_blender_scene_request(user_input):
            workspace = self._default_action_root()
            return self._guarded_action(
                "file_change",
                "create or update Blender scene",
                lambda: self.desktop_actions.create_blender_scene(workspace, user_input, self.user_settings.data),
            )

        local_path_result = self._try_local_path_action(user_input)
        if local_path_result is not None:
            return local_path_result

        parts = self._split_action_chain(user_input)
        if len(parts) > 1:
            category = self._chain_action_category(parts)
            title = " -> ".join(parts)

            def run_chain() -> str:
                messages: list[str] = []
                for part in parts:
                    result = self._execute_chained_action_part(part)
                    if result is None:
                        raise OSError(f'Neumim provest tento krok: "{part}"')
                    clean_result = result.rstrip(".")
                    if clean_result and clean_result not in messages:
                        messages.append(clean_result)
                return ". ".join(messages) + "."

            return self._guarded_action(category, f"chain action: {title}", run_chain)

        model_action_result = self._try_model_agent_action(user_input)
        if model_action_result is not None:
            return model_action_result

        return self._try_local_app_action(user_input)

    def _try_local_path_action(self, user_input: str) -> str | None:
        normalized = ascii_fold_text(" ".join(user_input.strip().split()))
        lowered = normalized.lower()
        if not normalized:
            return None

        browser_destination_match = re.fullmatch(
            r'(?:otevri|otev\?i|open|spust|spus\?|zapni|launch|start|jdi na|go to|naviguj na) '
            r'(?:mi )?(?:google chrome|chrome|chrom|prohlizec|browser)\s+'
            r'(?:a\s+)?(?:jdi na|go to|open|otevri|otev\?i|naviguj na|dej(?:\s+tam)?(?:\s+na)?|hod(?:\s+tam)?(?:\s+na)?)\s*(.+)$',
            normalized,
            flags=re.IGNORECASE,
        )
        if browser_destination_match:
            raw_target = browser_destination_match.group(1).strip().rstrip(".,;)]}\"'")
            raw_url = self._known_web_alias_url(raw_target) or raw_target
            return self._guarded_action(
                "app_launch",
                f"open url {raw_url}",
                lambda: self.desktop_actions.open_url(raw_url, prefer_chrome=True),
            )

        navigation_match = re.fullmatch(
            r'(?:jdi na|go to|naviguj na)\s+(.+)$',
            normalized,
            flags=re.IGNORECASE,
        )
        if navigation_match:
            raw_target = navigation_match.group(1).strip().rstrip(".,;)]}\"'")
            if raw_target.lower() in {"google chrome", "chrome", "chrom", "prohlizec", "browser"}:
                return self._guarded_action("app_launch", "open Chrome", lambda: self.desktop_actions.open_browser(prefer_chrome=True))
            raw_url = self._known_web_alias_url(raw_target) or raw_target
            if self._known_web_alias_url(raw_target) is not None or re.search(r"(https?://|localhost:|www\.|[a-z0-9-]+\.[a-z]{2,})", raw_url, flags=re.IGNORECASE):
                return self._guarded_action(
                    "app_launch",
                    f"open url {raw_url}",
                    lambda: self.desktop_actions.open_url(raw_url, prefer_chrome=True),
                )

        quick_web_target_match = re.fullmatch(
            r'(?:dej|hod) ?(?:mi )?(?:tam )?(?:na )?(.+)$',
            normalized,
            flags=re.IGNORECASE,
        )
        if quick_web_target_match:
            raw_target = self._clean_search_query(quick_web_target_match.group(1))
            raw_url = self._known_web_alias_url(raw_target) or raw_target
            if self._known_web_alias_url(raw_target) is not None or re.search(r"(https?://|localhost:|www\.|[a-z0-9-]+\.[a-z]{2,})", raw_url, flags=re.IGNORECASE):
                return self._guarded_action(
                    "app_launch",
                    f"open url {raw_url}",
                    lambda: self.desktop_actions.open_url(raw_url, prefer_chrome=True),
                )

        list_folder_patterns = [
            r'(?:vypis|ukaz|zobraz|list|show) (?:mi )?(?:obsah )?(?:slozky|slozku|folder|adresar) ?(.+)?$',
            r'(?:co je|co mam|co se nachazi) (?:ve|v) (?:slozce|folderu|adresari) (.+)$',
            r'(?:obsah slozky|folder contents) (.+)$',
        ]
        for pattern in list_folder_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            raw_target = str(match.group(1) or "").strip()
            target = self._resolve_pc_target(raw_target, prefer_directory=True)
            if target is None:
                return "Luna: Tu slozku jsem v pocitaci nenasla."
            return self._guarded_action("file_read", f"list folder {target}", lambda: self.desktop_actions.list_folder(target))

        read_file_patterns = [
            r'(?:precti|ukaz|zobraz|read|show) (?:mi )?(?:obsah )?(?:soubor|file) (.+)$',
            r'(?:co je v souboru|obsah souboru) (.+)$',
        ]
        for pattern in read_file_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            target = self._resolve_pc_target(match.group(1), prefer_directory=False)
            if target is None:
                return "Luna: Ten soubor jsem v pocitaci nenasla."
            return self._guarded_action("file_read", f"read file {target}", lambda: self.desktop_actions.read_text_file(target))

        system_info_match = re.fullmatch(
            r'(?:system info|get system info|info o systemu|informace o systemu|stav pc|pc info)',
            normalized,
            flags=re.IGNORECASE,
        )
        if system_info_match:
            return self._guarded_action("file_read", "get system info", lambda: self.desktop_actions.get_system_info())

        web_lookup_patterns = [
            r'(?:najdi|hledej|find|vyhledej|search) (?:mi )?(?:odkaz|link|url) (?:na|to) (.+)$',
            r'(?:najdi|hledej|find|vyhledej|search) (?:mi )?(?:stranku|stranka|web|website) (.+)$',
            r'(?:najdi|hledej|find|vyhledej|search) (?:mi )?(?:na webu|na internetu|online) (.+)$',
            r'(?:kde je|where is) (?:web|stranka|website|odkaz|link) (?:na|to)? ?(.+)$',
        ]
        for pattern in web_lookup_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            query = self._clean_search_query(match.group(1))
            if not query:
                return "Luna: Chybi, co mam hledat."
            known_url = self._known_web_alias_url(query)
            if known_url is not None:
                return self._guarded_action(
                    "app_launch",
                    f"open url {known_url}",
                    lambda: self.desktop_actions.open_url(known_url, prefer_chrome=True),
                )
            return self._guarded_action(
                "app_launch",
                f"search web for {query}",
                lambda: self.desktop_actions.search_web(query, prefer_chrome=True),
            )

        find_app_patterns = [
            r'(?:najdi|hledej|find) (?:mi )?(?:aplikaci|program|app) (.+)$',
            r'(?:kde je|where is) (?:aplikace|program|app) (.+)$',
        ]
        for pattern in find_app_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            query = self._clean_search_query(match.group(1))
            if not query:
                return "Luna: Chybi nazev aplikace, kterou mam hledat."
            app_key = self._known_app_key(query)
            if app_key:
                return self._guarded_action(
                    "file_read",
                    f"find app path {app_key}",
                    lambda: self.desktop_actions.describe_app_path(app_key, self.user_settings.data),
                )
            return self._guarded_action(
                "file_read",
                f"find app {query}",
                lambda: self.desktop_actions.find_paths(
                    self._pc_app_search_roots(),
                    query,
                    prefer_directory=None,
                    max_results=15,
                    max_scanned=12000,
                ),
            )

        find_path_patterns = [
            (r'(?:najdi|hledej|find) (?:mi )?(?:soubor|file) (.+)$', False),
            (r'(?:najdi|hledej|find) (?:mi )?(?:slozku|slo\?ku|folder|adresar) (.+)$', True),
            (r'(?:najdi|hledej|find) (?:mi )?(?:v pc|na pc|v pocitaci|on pc) (.+)$', None),
            (r'(?:najdi|hledej|find) (?:mi )?(?:v pocitaci|na pocitaci|in computer) (.+)$', None),
            (r'(?:kde je|where is) (.+)$', None),
        ]
        for pattern, prefer_directory in find_path_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            query = self._clean_search_query(match.group(1))
            if not query:
                return "Luna: Chybi nazev, ktery mam hledat."
            return self._guarded_action(
                "file_read",
                f"find {query}",
                lambda: self.desktop_actions.find_paths(self._pc_file_search_roots(), query, prefer_directory=prefer_directory),
            )

        url_match = re.search(r'(https?://\S+|localhost:\d+(?:/\S*)?|www\.\S+)', repair_text(user_input), flags=re.IGNORECASE)
        if url_match and any(token in lowered for token in ["otevri", "open", "spust", "spus?", "zapni", "launch"]):
            raw_url = url_match.group(1).strip().rstrip(".,;)]}\"'")
            prefer_chrome = any(token in lowered for token in ["chrome", "google chrome", "prohlizec", "browser"])
            return self._guarded_action("app_launch", f"open url {raw_url}", lambda: self.desktop_actions.open_url(raw_url, prefer_chrome=prefer_chrome))

        browser_match = re.fullmatch(
            r'(?:otevri|otev\?i|open|spust|spus\?|zapni|launch|start) (?:mi )?(?:google chrome|chrome|chrom|prohlizec|browser)',
            normalized,
            flags=re.IGNORECASE,
        )
        if browser_match:
            return self._guarded_action("app_launch", "open Chrome", lambda: self.desktop_actions.open_browser(prefer_chrome=True))

        open_known_folder_match = re.fullmatch(
            r'(?:otevri|otev\?i|open|spust|spus\?|zapni|launch|start) (?:mi )?(plochu|plocha|desktop|downloads|stazene|stazeni|stazene soubory|dokumenty|documents|obrazky|pictures|videa|videos|hudba|music)',
            normalized,
            flags=re.IGNORECASE,
        )
        if open_known_folder_match:
            target = self._resolve_known_user_folder(open_known_folder_match.group(1))
            if target is None:
                return "Luna: Tuhle systemovou slozku jsem v pocitaci nenasla."
            return self._guarded_action("path_open", f"open path {target}", lambda: self.desktop_actions.open_path(target))

        domain_match = re.fullmatch(
            r'(?:otevri|otev\?i|open|spust|spus\?|zapni|launch|start) (?:mi )?(?:odkaz|url|stranku|web|v chrome|in chrome)?\s*([a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/\S*)?)',
            normalized,
            flags=re.IGNORECASE,
        )
        if domain_match:
            raw_url = domain_match.group(1).strip()
            prefer_chrome = any(token in lowered for token in ["chrome", "google chrome"])
            return self._guarded_action("app_launch", f"open url {raw_url}", lambda: self.desktop_actions.open_url(raw_url, prefer_chrome=prefer_chrome))

        known_site_match = re.fullmatch(
            r'(?:otevri|otev\?i|open|spust|spus\?|zapni|launch|start) (?:mi )?([a-z0-9_-]+)',
            normalized,
            flags=re.IGNORECASE,
        )
        if known_site_match:
            raw_target = known_site_match.group(1).strip()
            known_url = self._known_web_alias_url(raw_target)
            if known_url is not None:
                return self._guarded_action(
                    "app_launch",
                    f"open url {known_url}",
                    lambda: self.desktop_actions.open_url(known_url, prefer_chrome=True),
                )

        search_match = re.search(
            r'(?:hledej na webu|hledej na google|najdi na webu|najdi na google|najdi online|vyhledej|hledej|search|google)(?: (?:v|ve|na) (?:chrome|google|webu|internetu))? (.+)$',
            normalized,
            flags=re.IGNORECASE,
        )
        if search_match:
            query = self._clean_search_query(search_match.group(1))
            if not query:
                return "Luna: Chybi hledany dotaz."
            prefer_chrome = any(token in lowered for token in ["chrome", "google chrome"])
            return self._guarded_action("app_launch", f"search web for {query}", lambda: self.desktop_actions.search_web(query, prefer_chrome=prefer_chrome))

        run_command_match = re.fullmatch(
            r'(?:(?:spust|spustit|spus\?|run) (?:mi )?(?:prikaz|p\?ikaz|command) )?'
            r'((?:npm start|npm install(?: [@a-zA-Z0-9._/\-]+){0,6}|npm i(?: [@a-zA-Z0-9._/\-]+){0,6}|npm run (?:dev|start|build|test)|python (?:main\.py|src[\\/ ]main\.py|app\.py)|python -m pytest|pytest|dir|echo .+))',
            normalized,
            flags=re.IGNORECASE,
        )
        if run_command_match:
            command_text = run_command_match.group(1).strip().replace("src main.py", "src/main.py")
            workspace = self._default_action_root()
            command_category = "dependency_install" if command_text.lower().startswith(("npm install", "npm i")) else "project_run"
            return self._guarded_action(
                command_category,
                f"run command {command_text}",
                lambda: self.desktop_actions.run_safe_command(command_text, workspace),
            )

        shortcut_match = re.fullmatch(
            r'(?:stiskni|zmackni|press) (?:klavesu |klavesovou zkratku |zkratku |key |shortcut )?([a-z0-9+\-\s]+)',
            normalized,
            flags=re.IGNORECASE,
        )
        if shortcut_match:
            shortcut = shortcut_match.group(1).strip().replace("-", "+")
            if not shortcut:
                return "Luna: Chybi klavesa nebo zkratka."
            return self._guarded_action("system_input", f"press shortcut {shortcut}", lambda: self.desktop_actions.press_shortcut(shortcut))

        click_match = re.fullmatch(
            r'(?:klikni|click) (?:na |at )?(?:x\s*=?\s*)?(\d{1,5})\s*(?:,|;|\s)\s*(?:y\s*=?\s*)?(\d{1,5})(?:\s*(left|right|middle|levym|pravym|prostrednim))?',
            normalized,
            flags=re.IGNORECASE,
        )
        if click_match:
            x_pos = int(click_match.group(1))
            y_pos = int(click_match.group(2))
            button_map = {"levym": "left", "pravym": "right", "prostrednim": "middle"}
            button = button_map.get(str(click_match.group(3) or "left").lower(), str(click_match.group(3) or "left").lower())
            return self._guarded_action("system_input", f"mouse click {x_pos},{y_pos}", lambda: self.desktop_actions.mouse_click(x_pos, y_pos, button=button))

        email_match = re.search(
            r'\b(?:posli|po\?li|odesli|ode\?li|napis|napi\?|priprav|vytvor|send|write|draft) (?:mi )?(?:e-?mail|mail)\b|\b(?:e-?mail|mail) (?:na|to)\b',
            normalized,
            flags=re.IGNORECASE,
        )
        if email_match:
            details = self._extract_email_details(user_input)
            recipient_label = details["recipient"] or "recipient to fill in"

            def create_email_draft() -> str:
                workspace = self._default_action_root()
                message = self.desktop_actions.create_email_draft(
                    workspace,
                    recipient=details["recipient"],
                    subject=details["subject"],
                    body=details["body"],
                )
                return (
                    f"{message} Email jsem neodeslala automaticky. "
                    "Nejdřív ho zkontroluj a odešli ručně ve své emailové aplikaci."
                )

            return self._guarded_action("communication", f"draft email to {recipient_label}", create_email_draft)

        type_text_match = re.search(
            r'(?:napis|napiš|type|write) (?:mi )?(?:text |do aktivniho okna |do okna |into active window )?["“](.+?)["”]$',
            repair_text(user_input),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not type_text_match:
            type_text_match = re.search(
                r'(?:napis|napi\?|type|write) (?:mi )?(?:text|do aktivniho okna|do okna|into active window)\s+(.+)$',
                normalized,
                flags=re.IGNORECASE | re.DOTALL,
            )
        if type_text_match:
            text_to_type = repair_text(type_text_match.group(1)).strip()
            if not text_to_type:
                return "Luna: Chybi text, ktery mam napsat."
            return self._guarded_action("system_input", "type text into active window", lambda: self.desktop_actions.type_text(text_to_type))

        scripts_match = re.fullmatch(
            r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make|priprav|prepare) (?:projektove |project )?(?:skripty|skripty\.?|scripts?|srcipts|scriots|bat skripty|bat scripts)(?: .*)?',
            normalized,
            flags=re.IGNORECASE,
        )
        if scripts_match:
            open_in_vscode = self._mentions_vscode(normalized)

            def create_scripts() -> str:
                workspace = self._default_action_root()
                message = self.desktop_actions.create_project_scripts(workspace)
                if open_in_vscode:
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, workspace / "scripts")
                    return f"{message} {vscode_message}."
                return message

            return self._guarded_action("file_change", "create project scripts", create_scripts)

        run_web_match = re.fullmatch(
            r'(?:(?:spust|spustit|spus\?|pust|pustit|zapni|start|run) (?:mi )?(?:web|webovy server|web server|website|stranku|stranka)(?: .*)?|(?:otevri|otev\?i|open) (?:localhost|web na localhostu)(?: .*)?)',
            normalized,
            flags=re.IGNORECASE,
        )
        if run_web_match:
            port_match = re.search(r'(?:port|:)\s*(\d{2,5})', normalized, flags=re.IGNORECASE)
            port = int(port_match.group(1)) if port_match else 8000
            web_folder = self._find_named_target("web", prefer_directory=True) or self._find_recent_workspace_target("web", prefer_directory=True)
            if web_folder is None:
                return "Luna: Nenasla jsem slozku web, takze nemam co spustit."

            def run_web_server() -> dict[str, object]:
                return self.desktop_actions.run_static_web_server(web_folder, port=port)  # type: ignore

            return self._guarded_action("project_run", f"run static web server {web_folder} on port {port}", run_web_server)

        run_project_match = re.fullmatch(
            r'(?:(?:spust|spustit|spus\?)(?: (?:projekt|project|workspace|aplikaci|app|to|tento projekt))?|(?:start|run) (?:project|workspace|app|application))',
            normalized,
            flags=re.IGNORECASE,
        )
        if run_project_match:
            workspace = self._default_action_root()

            def run_project() -> dict[str, object]:
                return self.desktop_actions.run_project(workspace)  # type: ignore

            return self._guarded_action("project_run", f"run project {workspace}", run_project)

        calculator_match = re.search(
            r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) (?:python )?(?:kalkulacku|kalkula\?ku|calculator)(?: .*)?$',
            normalized,
            flags=re.IGNORECASE,
        )
        if calculator_match:
            open_in_vscode = self._mentions_vscode(normalized)

            def create_calculator() -> str:
                workspace = self._default_action_root()
                message = self.desktop_actions.create_python_calculator(workspace)
                if open_in_vscode:
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, workspace)
                    return f"{message} {vscode_message}."
                return message

            return self._guarded_action("file_change", "create python calculator", create_calculator)

        blender_scene_requested = self._looks_like_blender_scene_request(user_input) or (
            "blender" in lowered
            and any(token in lowered for token in ["vytvor", "udelej", "create", "make", "postav", "build", "model", "scenu", "scene", "3d"])
        ) or bool(
            re.search(
                r'(?:vytvor|udelej|create|make|postav|build) (?:mi )?(?:3d )?(?:model|scenu|scene|asset)(?: .*)?$',
                normalized,
                flags=re.IGNORECASE,
            )
        )
        if blender_scene_requested:
            def create_blender_scene() -> dict[str, object]:
                workspace = self._default_action_root()
                return self.desktop_actions.create_blender_scene(workspace, user_input, self.user_settings.data)  # type: ignore[return-value]

            return self._guarded_action("file_change", "create Blender scene", create_blender_scene)

        project_blueprints = [
            (r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) python projekt (.+?)(?: a otevri ve vscode| and open in vscode)?$', "python"),
            (r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) web projekt (.+?)(?: a otevri ve vscode| and open in vscode)?$', "web"),
            (r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) electron projekt (.+?)(?: a otevri ve vscode| and open in vscode)?$', "electron"),
        ]
        for pattern, kind in project_blueprints:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            project_name = match.group(1).strip().strip('"').strip("'")
            if not project_name:
                return "Luna: Chybi nazev projektu."
            open_in_vscode = self._mentions_vscode(normalized)

            def run_project_creation() -> str:
                if kind == "python":
                    workspace = self.desktop_actions.create_python_project(project_name)
                elif kind == "web":
                    workspace = self.desktop_actions.create_web_project(project_name)
                elif kind == "electron":
                    workspace = self.desktop_actions.create_electron_project(project_name)
                else:
                    workspace = self.desktop_actions.create_electron_project(project_name)
                if open_in_vscode:
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, workspace)
                    return f"Created {kind} project {workspace}. {vscode_message}."
                return f"Created {kind} project {workspace}."

            return self._guarded_action("file_change", f"create {kind} project {project_name}", run_project_creation)

        web_page_match = re.search(
            r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make|postav|build) (?:mi )?(?:jednoduchy |simple |portfolio |landing |webovy |webovou )*(?:web|website|stranku|stranka|webovou stranku|landing page|portfolio)(?: .*)?$',
            normalized,
            flags=re.IGNORECASE,
        )
        if web_page_match and "web projekt" not in lowered:
            explain_requested = any(token in lowered for token in ["vysvetli", "vysv?tli", "explain", "popis", "popsat"])
            open_in_vscode = self._mentions_vscode(normalized)

            def create_web_page() -> str:
                workspace = self._default_action_root()
                message = self.desktop_actions.create_simple_web_page(workspace, description=user_input)
                web_folder = workspace / "web"
                index_file = web_folder / "index.html"
                expected_files = [
                    web_folder / "index.html",
                    web_folder / "styles.css",
                    web_folder / "script.js",
                    web_folder / "README.md",
                ]
                missing_files = [path.name for path in expected_files if not path.exists()]
                if missing_files:
                    message = f"{message} Ověření: chybí {', '.join(missing_files)}."
                else:
                    message = f"{message} Ověřeno: web/index.html, web/styles.css, web/script.js a web/README.md existují."

                if self._is_action_allowed("path_open"):
                    try:
                        self.desktop_actions.open_path(index_file)
                        message = f"{message} Náhled jsem otevřela v prohlížeči."
                    except OSError as error:
                        message = f"{message} Náhled se nepodařilo otevřít automaticky: {error}"
                else:
                    message = f"{message} Náhled najdeš tady: {index_file}"

                if open_in_vscode and self.user_settings.data.vscode_path.strip() and self._is_action_allowed("app_launch"):
                    try:
                        vscode_message = self.desktop_actions.open_web_folder_in_vscode(self.user_settings.data.vscode_path, web_folder)
                        message = f"{message} {vscode_message}."
                    except OSError as error:
                        message = f"{message} VS Code se nepodařilo otevřít automaticky: {error}"
                else:
                    message = f"{message} Ve VS Code otevři složku: {web_folder}"
                if not open_in_vscode and " Ve VS Code " in message:
                    message = message.rsplit(" Ve VS Code ", 1)[0].rstrip()
                if explain_requested:
                    explanation = (
                        "Vysvětlení: `web/index.html` drží obsah stránky, "
                        "`web/styles.css` řeší vzhled a responzivitu, "
                        "`web/script.js` přidává malou interakci. "
                        "Náhled otevřeš dvojklikem na `web/index.html` nebo přes Live Server ve VS Code."
                    )
                    return f"{message} {explanation}"
                return message

            return self._guarded_action("file_change", "create simple web page", create_web_page)

        rewrite_patterns = [r'(?:prepis|p\?epis|rewrite|overwrite) (?:soubor|file) (.+?) (?:s obsahem|with content) (.+)$']
        for pattern in rewrite_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            target = self._resolve_creation_target(match.group(1))
            content = match.group(2)
            return self._guarded_action("file_change", f"overwrite file {target}", lambda: self.desktop_actions.overwrite_file(target, content))

        append_patterns = [r'(?:pridej do|p\?idej do|append to) (?:souboru|soubor|file) (.+?) (?:obsah|content) (.+)$']
        for pattern in append_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            target = self._resolve_creation_target(match.group(1))
            content = match.group(2)
            return self._guarded_action("file_change", f"append to file {target}", lambda: self.desktop_actions.append_to_file(target, content))

        multi_file_match = re.search(
            r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) (?:soubory|files) (.+?)(?: (?:a )?otevri ve vscode| (?:and )?open in vscode)?$',
            normalized,
            flags=re.IGNORECASE,
        )
        if multi_file_match:
            raw_targets = multi_file_match.group(1)
            open_in_vscode = self._mentions_vscode(normalized)
            parts = [part.strip().strip('"').strip("'") for part in re.split(r",|;", raw_targets) if part.strip()]
            if not parts:
                return "Luna: Chybi seznam souboru."
            targets = {self._resolve_creation_target(part): "" for part in parts}

            def create_many_files() -> str:
                message = self.desktop_actions.create_files_batch(targets)
                if open_in_vscode:
                    first_target = next(iter(targets.keys()))
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, first_target)
                    return f"{message} {vscode_message}."
                return message

            return self._guarded_action("file_change", f"create files {', '.join(parts)}", create_many_files)
        rich_file_match = re.search(
            r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) (?:soubor|file) (.+?) (?:s obsahem|with content) (.+?)(?: (?:a )?otevri ve vscode| (?:and )?open in vscode)?$',
            normalized,
            flags=re.IGNORECASE,
        )
        if rich_file_match:
            target = self._resolve_creation_target(rich_file_match.group(1))
            content = rich_file_match.group(2)
            open_in_vscode = self._mentions_vscode(normalized)

            def create_rich_file() -> str:
                message = self.desktop_actions.create_file(target, content)
                if open_in_vscode:
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, target)
                    return f"{message}. {vscode_message}."
                return message

            return self._guarded_action("file_change", f"create file {target}", create_rich_file)

        create_folders_match = re.search(
            r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) (?:slozky|slo\?ky|folders)(?: (.+?))?$',
            normalized,
            flags=re.IGNORECASE,
        )
        if create_folders_match:
            raw_targets = str(create_folders_match.group(1) or "").strip()
            folder_names = self._parse_folder_names(raw_targets)
            if not folder_names:
                folder_names = ["src", "docs", "tests", "scripts"]
            open_in_vscode = self._mentions_vscode(normalized)

            def create_many_folders() -> str:
                workspace = self._default_action_root()
                targets = [(workspace / folder_name).resolve() for folder_name in folder_names]
                message = self.desktop_actions.create_folders_batch(targets)
                if open_in_vscode:
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, workspace)
                    return f"{message} {vscode_message}."
                return message

            return self._guarded_action("file_change", f"create folders {', '.join(folder_names)}", create_many_folders)

        create_folder_patterns = [r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) (?:slozku|slo\?ku|folder|adresar|adres\?\?) (.+)$']
        for pattern in create_folder_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            target = self._resolve_creation_target(match.group(1))
            return self._guarded_action("file_change", f"create folder {target}", lambda: self.desktop_actions.create_folder(target))

        create_file_patterns = [r'(?:vytvor|vytvo\?|udelej|ud\?lej|create|make) (?:soubor|file) (.+)$']
        for pattern in create_file_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            raw_target = match.group(1)
            open_in_vscode = self._mentions_vscode(raw_target)
            if open_in_vscode:
                raw_target = re.sub(r'(?:a )?otevri ve vscode|(?:and )?open in vscode', '', raw_target, flags=re.IGNORECASE).strip()
            target = self._resolve_creation_target(raw_target)

            def create_file_action() -> str:
                message = self.desktop_actions.create_file(target)
                if open_in_vscode:
                    vscode_message = self.desktop_actions.open_in_vscode(self.user_settings.data.vscode_path, target)
                    return f"{message}. {vscode_message}."
                return message

            return self._guarded_action("file_change", f"create file {target}", create_file_action)

        direct_path_match = re.search(r'([A-Za-z]:[\\/][^"]+)', normalized)
        if direct_path_match and any(token in lowered for token in ["otevri", "otev?i", "open", "spust", "spus?"]):
            target = self._resolve_local_target(direct_path_match.group(1))
            if target is not None:
                return self._guarded_action("path_open", f"open path {target}", lambda: self.desktop_actions.open_path(target))
            return "Luna: Tu cestu jsem v pocitaci nenasla."

        wants_open = any(token in lowered for token in ["otevri", "otev?i", "open", "spust", "spus?"])
        wants_web = any(token in lowered for token in [" web", "web ", "webu", "website", "stranku", "stranka"])
        if wants_open and wants_web and self._mentions_vscode(normalized):
            web_target = self._find_named_target("web", prefer_directory=True) or self._find_recent_workspace_target("web", prefer_directory=True)
            if web_target is None:
                return "Luna: Slozku web jsem v projektu nenasla."

            def open_web_in_vscode() -> str:
                return self.desktop_actions.open_web_folder_in_vscode(self.user_settings.data.vscode_path, web_target)

            return self._guarded_action("app_launch", f"open web folder in VS Code {web_target}", open_web_in_vscode)

        command_patterns = [
            (r'(?:otevri|otev\?i|open) (?:soubor|file) (.+)$', False),
            (r'(?:otevri|otev\?i|open) (?:slozku|slo\?ku|folder|adresar|adres\?\?) (.+)$', True),
            (r'(?:spust|spus\?) (?:soubor|file|path|cestu) (.+)$', False),
        ]
        for pattern, prefer_directory in command_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            raw_target = match.group(1)
            target = self._resolve_local_target(raw_target)
            if target is None:
                target = self._find_named_target(raw_target, prefer_directory=prefer_directory)
            if target is None:
                return "Luna: Ten soubor nebo slozku jsem v pocitaci nenasla."
            return self._guarded_action("path_open", f"open path {target}", lambda: self.desktop_actions.open_path(target))

        if any(phrase in lowered for phrase in ["otevri workspace ve vscode", "otev?i workspace ve vscode", "open workspace in vscode", "otevri projekt ve vscode", "otev?i projekt ve vscode", "open project in vscode"]):
            current_project = self.projects.get_current_project()
            if current_project is None:
                return "Luna: Ted nemam aktivni projekt, takze nemam co otevrit ve VS Code."

            def open_workspace_in_vscode() -> str:
                result = self.open_connected_app("vscode", current_project.name)
                message = str(result.get("message", "")).strip()
                if result.get("ok"):
                    return message
                raise OSError(message or "VS Code jsem nemohla otevrit.")

            return self._guarded_action("app_launch", f"open workspace in VS Code for {current_project.name}", open_workspace_in_vscode)

        if any(phrase in lowered for phrase in ["otevri projekt", "otev?i projekt", "open project", "otevri workspace", "otev?i workspace", "open workspace"]):
            current_project = self.projects.get_current_project()
            if current_project is None:
                return "Luna: Ted nemam aktivni projekt, takze nemam co otevrit."
            workspace = self.desktop_actions.ensure_project_workspace(current_project.name)
            return self._guarded_action("path_open", f"open workspace {workspace}", lambda: self.desktop_actions.open_path(workspace))

        return None

    def _try_local_app_action(self, user_input: str) -> str | None:
        normalized = ascii_fold_text(" ".join(user_input.strip().lower().split()))
        if not normalized:
            return None

        app_aliases = {
            "vscode": ["vscode", "vs code", "vscodu", "vs codu", "visual studio code", "code.exe"],
            "blender": ["blender"],
            "unreal": ["unreal", "unreal engine", "unreal engine 5", "ue5"],
            "unity": ["unity"],
            "photoshop": ["photoshop"],
            "davinci": ["davinci", "davinci resolve"],
            "premiere": ["premiere", "premiere pro"],
            "after_effects": ["after effects", "aftereffects"],
            "figma": ["figma"],
            "fl_studio": ["fl studio"],
            "substance": ["substance", "substance painter", "substance 3d painter"],
        }
        open_markers = [
            "otevri", "otevrit", "otev?", "otev?e", "otevrel", "otevrela",
            "spust", "spustit", "zapni", "zapnout",
            "open", "launch", "start",
        ]
        if not any(marker in normalized for marker in open_markers):
            return None

        for app_key, aliases in app_aliases.items():
            if any(alias in normalized for alias in aliases):
                project_name = ""
                if app_key != "vscode":
                    current_project = self.projects.get_current_project()
                    project_name = current_project.name if current_project is not None else ""

                def launch_app() -> str:
                    result = self.open_connected_app(app_key, project_name, log_result=False)
                    message = str(result.get("message", "")).strip()
                    if result.get("ok"):
                        return message
                    raise OSError(message or "Aplikaci se nepodarilo otevrit.")

                return self._guarded_action("app_launch", f"open {app_key}", launch_app)

        # Resolve an explicit app-opening command against the installed app list.
        match = re.fullmatch(r"(?:prosim )?(?:otevri|spust|zapni|open|launch|start) (?:mi )?(?:aplikaci |program )?(.+?)[.!?]*", normalized)
        if match:
            try:
                item = find_registered_app(match.group(1))
            except (OSError, ValueError, RuntimeError):
                item = None
            if item:
                def launch_registered() -> str:
                    result = self.open_connected_app(item['key'], '', log_result=False)
                    if not result.get('ok'): raise OSError(result.get('message', 'Spuštění selhalo.'))
                    return str(result['message'])
                return self._guarded_action('app_launch', f"open {item['title']}", launch_registered)

        return None

    def _project_context(self) -> str:
        project = self.projects.get_current_project()
        if project is None:
            return ""

        lines = [
            f"Project name: {project.name}",
            f"Current phase: {project.current_phase}",
            f"Project brief: {project.brief}",
        ]
        if project.next_step:
            lines.append(f"Next step: {project.next_step}")
        if project.tasks:
            top_tasks = []
            for task in project.tasks[:4]:
                title = task.get("title", "Task")
                status = task.get("status", "pending")
                top_tasks.append(f"{title} [{status}]")
            lines.append("Tracked tasks: " + ", ".join(top_tasks))
        memory_sections = self._project_memory_sections(project)
        if memory_sections["handoff"]:
            lines.append("Recent handoff: " + " | ".join(memory_sections["handoff"][:2]))
        if memory_sections["execution"]:
            lines.append("Recent execution: " + " | ".join(memory_sections["execution"][:2]))
        if memory_sections["focus"]:
            lines.append("Recent conversation focus: " + " | ".join(memory_sections["focus"][:2]))
        if project.attachment_names:
            lines.append("Linked files: " + ", ".join(project.attachment_names[:6]))
        lines.append("If the user asks a vague follow-up and no new project is explicitly introduced, assume they still mean this active project.")
        return "\n".join(lines)

    def _context_snippet(self, text: object, limit: int = 140) -> str:
        cleaned = repair_text(str(text or "")).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if len(cleaned) > limit:
            cleaned = cleaned[: limit - 3].rstrip() + "..."
        return cleaned

    def _session_context(self) -> str:
        history = self.memory.load_history()
        lines: list[str] = []

        chat_title = self.memory.get_current_session_title().strip()
        if chat_title:
            lines.append(f"Current chat title: {chat_title}")

        current_voice = self._current_conversation_speaker()
        if current_voice:
            lines.append(f"Current active voice in this chat: {current_voice}")

        last_user_message = ""
        last_assistant_message = ""
        for item in reversed(history):
            role = str(item.get("role", "")).strip().lower()
            content = self._context_snippet(item.get("content", ""), limit=180)
            if not content:
                continue
            if role == "user" and not last_user_message:
                last_user_message = content
            elif role == "assistant" and not last_assistant_message:
                last_assistant_message = content
            if last_user_message and last_assistant_message:
                break

        if last_user_message:
            lines.append(f"Most recent user topic: {last_user_message}")
        if last_assistant_message:
            lines.append(f"Most recent assistant direction: {last_assistant_message}")

        if self.pending_action is not None:
            pending_title = self._context_snippet(self.pending_action[0], limit=80)
            if pending_title:
                lines.append(f"Pending action waiting for confirmation: {pending_title}")

        recent_actions = self.action_log.recent(2)
        if recent_actions:
            action_items: list[str] = []
            for entry in reversed(recent_actions):
                title = self._context_snippet(entry.title, limit=60)
                if not title:
                    continue
                action_items.append(f"{title} [{entry.status}]")
            if action_items:
                lines.append("Recent local actions: " + " | ".join(action_items))

        if self.observe_mode_enabled:
            lines.append("Observe mode is enabled, so desktop context may still matter for follow-up questions.")

        lines.append(
            "If the user sends a short follow-up, assume they still mean the current topic in this chat unless they clearly switch topics."
        )
        return "\n".join(lines)

    def _library_context(self, user_input: str) -> str:
        workspace = self.user_settings.data
        if bool(workspace.cloud_enabled) and bool(workspace.cloud_auto_sync) and workspace.cloud_root_path.strip():
            self.library.sync_folder(workspace.cloud_root_path.strip())
        return self.library.relevant_context(user_input)

    def _remember_project_chat_focus(self, user_input: str, response: str) -> None:
        project = self.projects.get_current_project()
        if project is None:
            return
        cleaned_input = " ".join(user_input.strip().split())
        if not cleaned_input or cleaned_input.startswith("/"):
            return
        note = cleaned_input[:140]
        if len(cleaned_input) > 140:
            note += "..."
        self.projects.add_memory_entry(project.id, f"Chat focus: {note}")
        if response:
            cleaned_response = response.removeprefix("Luna: ").strip()
            if cleaned_response:
                short_response = cleaned_response[:160]
                if len(cleaned_response) > 160:
                    short_response += "..."
                self.projects.add_memory_entry(project.id, f"Luna direction: {short_response}")

    def get_runtime_status(self) -> str:
        return self.runtime_status.format()

    def get_memory_insights(self) -> str:
        return self.memory_coordinator.memory_insights()

    def build_prompt(
        self,
        user_input: str,
        mode: str,
        instruction: str = "",
        internet_context: str = "",
        selected_mode: str = "auto",
        reasoning_box: str = "black_box",
        hidden_support: str = "",
        project_context: str = "",
        library_context: str = "",
        session_context: str = "",
        intelligence_level: str | None = None,
        include_history: bool = True,
    ) -> list[dict[str, str]]:
        level = str(intelligence_level or self._normalized_intelligence_level()).strip()
        return self.prompt_builder.build(
            user_input=user_input,
            mode=mode,
            instruction=instruction,
            internet_context=internet_context,
            selected_mode=selected_mode,
            reasoning_box=reasoning_box,
            hidden_support=hidden_support,
            project_context=project_context,
            library_context=library_context,
            session_context=session_context,
            intelligence_level=level,
            include_history=include_history,
        )

    def build_messages(
        self,
        user_input: str,
        mode: str,
        instruction: str = "",
        internet_context: str = "",
        selected_mode: str = "auto",
        reasoning_box: str = "black_box",
        hidden_support: str = "",
        project_context: str = "",
        library_context: str = "",
        session_context: str = "",
        intelligence_level: str | None = None,
        include_history: bool = True,
    ) -> list[dict[str, str]]:
        return self.build_prompt(
            user_input=user_input,
            mode=mode,
            instruction=instruction,
            internet_context=internet_context,
            selected_mode=selected_mode,
            reasoning_box=reasoning_box,
            hidden_support=hidden_support,
            project_context=project_context,
            library_context=library_context,
            session_context=session_context,
            intelligence_level=intelligence_level,
            include_history=include_history,
        )

    def _is_live_visual_query(self, user_input: str) -> bool:
        normalized = " ".join(str(user_input or "").strip().lower().split())
        if not normalized:
            return False
        triggers = (
            "co vidis",
            "co vidiš",
            "co vidis ted",
            "co vidiš ted",
            "co je na obrazovce",
            "co je ted na obrazovce",
            "vidis moje prostredi",
            "vidiš moje prostředí",
            "what do you see",
            "what do you see now",
            "what is on the screen",
            "what is on screen",
            "describe the screen",
        )
        return any(trigger in normalized for trigger in triggers)

    def chat(self, user_input: str, *, extra_context: str = "") -> str:
        self._reload_runtime_preferences()
        self.last_coordination = {
            "lunaActive": False,
            "xenoActive": False,
            "tracks": [],
        }
        self._active_agent_route = None
        cleaned_input = repair_text(str(user_input or "")).strip()
        extra_context = repair_text(str(extra_context or "")).strip()
        if not cleaned_input:
            return ""
        if cleaned_input.lower() == "exit":
            return "Luna: Dobre. Az budes chtit pokracovat, jsem tady 🙂"

        initial_route = self.agent_router.route(
            cleaned_input,
            extra_context=extra_context,
            current_action_mode=self._action_mode(),
            xeno_consulted=False,
        )
        self._active_agent_route = initial_route
        self._trace_agent(
            phase="route",
            status="selected",
            detail=initial_route.reason,
            metadata={
                "source": initial_route.input_source,
                "scope": initial_route.action_scope,
                "force_auto_execution": initial_route.force_auto_execution,
                "live_visual_query": initial_route.live_visual_query,
            },
        )
        self.agent_run_state.start(
            user_input=cleaned_input,
            input_source=initial_route.input_source,
            owner="Xeno" if initial_route.consult_xeno and initial_route.action_scope != "conversation" else "Luna",
            scope=initial_route.action_scope,
            risk=initial_route.risk,
            vision_active=initial_route.vision_active,
            xeno_active=initial_route.consult_xeno,
            status="routed",
            note=initial_route.reason,
        )

        pending_action_result = self._handle_pending_action_command(cleaned_input)
        if pending_action_result is not None:
            self.memory_coordinator.remember_user_input(cleaned_input, "action")
            self.memory_coordinator.save_exchange(cleaned_input, pending_action_result)
            return pending_action_result

        if initial_route.action_scope == "blocked_risk":
            blocked_response = (
                "Luna: Tuhle rizikovou akci nespustím automaticky. "
                "Vypadá jako mazání nebo zásah do systému, takže ji držím zablokovanou. 🙂"
            )
            self._log_action("system", cleaned_input[:120], "blocked", initial_route.reason)
            self._trace_agent(
                phase="route",
                status="blocked",
                detail=initial_route.reason,
                metadata={"user_input": cleaned_input[:180]},
            )
            self.agent_run_state.update(status="blocked", final_message=blocked_response, note="Risk guardrail blocked the request.")
            self.memory_coordinator.remember_user_input(cleaned_input, "action")
            self.memory_coordinator.save_exchange(cleaned_input, blocked_response)
            return blocked_response

        internet_result = self._handle_internet_command(cleaned_input)
        if internet_result is not None:
            return internet_result

        screen_share_help_result = self._handle_screen_share_help_command(cleaned_input)
        if screen_share_help_result is not None:
            self.memory_coordinator.remember_user_input(cleaned_input, "support")
            self.memory_coordinator.save_exchange(cleaned_input, screen_share_help_result)
            return screen_share_help_result

        local_capability_result = self._handle_local_capability_command(cleaned_input)
        if local_capability_result is not None:
            self.memory_coordinator.remember_user_input(cleaned_input, "support")
            self.memory_coordinator.save_exchange(cleaned_input, local_capability_result)
            return local_capability_result

        observation_result = self._handle_observation_command(cleaned_input)
        if observation_result is not None:
            self.memory_coordinator.remember_user_input(cleaned_input, "action")
            self.memory_coordinator.save_exchange(cleaned_input, observation_result)
            return observation_result

        if initial_route.should_attempt_local_action or self._looks_like_blender_scene_request(cleaned_input):
            original_override = self._action_mode_override
            if initial_route.force_auto_execution and original_override is None:
                self._action_mode_override = "auto"
            try:
                local_action_result = self._try_local_action(cleaned_input)
            finally:
                if initial_route.force_auto_execution and original_override is None:
                    self._action_mode_override = original_override

            if local_action_result is not None:
                self.memory_coordinator.remember_user_input(cleaned_input, "action")
                self.memory_coordinator.save_exchange(cleaned_input, local_action_result)
                self._remember_project_chat_focus(cleaned_input, local_action_result)
                return local_action_result

        workflow_data = self.workflow.process(cleaned_input, self.memory.load_history())
        if workflow_data["system_message"]:
            return f"Luna: {workflow_data['system_message']}"

        # Ensure workflow_data values are strings (not None)
        workflow_user_input: str = str(workflow_data.get("user_input") or cleaned_input)
        mode: str = str(workflow_data.get("mode") or "auto")
        
        selected_mode: str = str(workflow_data.get("selected_mode") or mode or "auto")
        self.memory_coordinator.remember_user_input(cleaned_input, selected_mode)

        self._last_support_model_source = "unused"
        self._last_primary_model_source = "nvidia" if self.settings.model_type == "nvidia" else "lm_studio"
        xeno_requested = self.xeno.should_consult(workflow_user_input)
        agent_route = self.agent_router.route(
            workflow_user_input,
            extra_context=extra_context,
            current_action_mode=self._action_mode(),
            xeno_consulted=xeno_requested,
        )
        self._active_agent_route = agent_route
        xeno_consulted = agent_route.consult_xeno
        self._trace_agent(
            phase="route",
            status="orchestrated",
            detail=agent_route.reason,
            metadata={
                "source": agent_route.input_source,
                "scope": agent_route.action_scope,
                "xeno_consulted": xeno_consulted,
                "vision_active": agent_route.vision_active,
            },
        )
        response_author = self._response_author(workflow_user_input, xeno_consulted=xeno_consulted)
        self.agent_run_state.update(owner=response_author, xeno_active=xeno_consulted, status="thinking")
        internet_context = self._internet_context(workflow_user_input)
        hidden_xeno_support = self._hidden_xeno_support(workflow_user_input)
        automation_summary = "\n".join(
            part
            for part in [
                self.xeno.build_automation_summary(workflow_user_input),
                agent_route.summary,
                self.tool_registry.summary_for_prompt(agent_route.action_scope),
            ]
            if str(part or "").strip()
        )
        observer_context = ""
        if self.observe_mode_enabled:
            observer_context = self._observer_context(refresh=self._observer_refresh_enabled())
        coordination = self._build_internal_coordination(
            user_input=workflow_user_input,
            response_author=response_author,
            xeno_consulted=xeno_consulted,
            automation_summary=automation_summary,
            hidden_support=hidden_xeno_support,
        )
        project_context = self._project_context()
        library_context = self._library_context(workflow_user_input)
        session_context = self._session_context()
        live_visual_query = agent_route.live_visual_query
        voice_mode = agent_route.input_source == "voice"
        orchestrated = self.orchestrator.build(
            user_input=workflow_user_input,
            base_instruction=str(workflow_data.get("instruction", "") or ""),
            response_author=response_author,
            xeno_consulted=xeno_consulted,
            coordination=coordination,
            hidden_xeno_support=hidden_xeno_support,
            automation_summary=automation_summary,
            extra_context=extra_context,
            observer_context=observer_context,
            session_context=session_context,
            live_visual_query=live_visual_query,
            voice_mode=voice_mode,
        )
        self.last_coordination = orchestrated.coordination
        intelligence_level = self._normalized_intelligence_level()
        messages = self.build_messages(
            user_input=user_input,
            mode=mode,
            instruction=orchestrated.instruction,
            internet_context=internet_context,
            selected_mode=selected_mode,
            reasoning_box=str(workflow_data.get("reasoning_box") or self.settings.default_reasoning_box),
            hidden_support=orchestrated.hidden_support,
            project_context=project_context,
            library_context=library_context,
            session_context=orchestrated.session_context,
            intelligence_level=intelligence_level,
            include_history=orchestrated.include_history,
        )

        if response_author == "Xeno":
            response = self._generate_xeno_response(messages)
        else:
            response = self._generate_primary_response(messages)
        structured_action_result = self._try_structured_action_response(cleaned_input, str(response or ""))
        if structured_action_result is not None:
            self.memory_coordinator.remember_user_input(cleaned_input, "action")
            self.memory_coordinator.save_exchange(cleaned_input, structured_action_result)
            self._remember_project_chat_focus(cleaned_input, structured_action_result)
            return structured_action_result
        if not str(response).strip():
            response = "Luna: Tentokrat z modelu nic rozumneho neprislo. Zkus to prosim jeste jednou 🙂"
        debug_footer = self._build_model_debug_footer(xeno_consulted=xeno_consulted)
        self.last_model_debug = debug_footer
        response = str(response).rstrip()
        self._trace_agent(
            phase="response",
            status="completed",
            detail=f"Final speaker: {response_author}. Response length: {len(response)} chars.",
            metadata={
                "response_author": response_author,
                "primary_model_source": self._last_primary_model_source,
                "support_model_source": self._last_support_model_source,
            },
        )
        self.agent_run_state.update(status="completed", owner=response_author, final_message=response)
        self.memory_coordinator.save_exchange(cleaned_input, response, assistant_author=response_author)
        self._remember_project_chat_focus(cleaned_input, response)
        return response

    def process_message(self, user_input: str) -> str:
        return self.chat(user_input)

    def list_chats(self) -> list[dict[str, str]]:
        return self.memory.list_sessions()

    def create_new_chat(self, title: str = "New chat") -> str:
        return self.memory.create_session(title)

    def switch_chat(self, session_id: str) -> list[dict[str, str]]:
        return self.memory.switch_session(session_id)

    def delete_chat(self, session_id: str) -> str:
        return self.memory.delete_session(session_id)

    def rename_chat(self, session_id: str, title: str) -> str:
        return self.memory.rename_session(session_id, title)

    def get_current_chat_id(self) -> str:
        return self.memory.get_current_session_id()

    def get_current_chat_title(self) -> str:
        return self.memory.get_current_session_title()


    def list_library_entries(self) -> list[dict[str, str]]:
        return self.library.list_entries()

    def add_library_note(self, title: str, content: str, tags: list[str] | None = None) -> dict[str, str]:
        entry = self.library.add_note(title, content, tags)
        return {
            "id": entry.id,
            "title": entry.title,
            "kind": entry.kind,
            "source": entry.source,
            "preview": entry.content[:120],
        }

    def add_library_link(self, title: str, url: str, tags: list[str] | None = None) -> dict[str, str]:
        entry = self.library.add_link(title, url, tags)
        return {
            "id": entry.id,
            "title": entry.title,
            "kind": entry.kind,
            "source": entry.source,
            "preview": entry.content[:120],
        }

    def add_library_file(self, file_path: str, tags: list[str] | None = None) -> dict[str, str] | None:
        entry = self.library.add_file(file_path, tags)
        if entry is None:
            return None
        return {
            "id": entry.id,
            "title": entry.title,
            "kind": entry.kind,
            "source": entry.source,
            "preview": entry.content[:120],
        }

    def remove_library_entry(self, entry_id: str) -> bool:
        return self.library.remove_entry(entry_id)

    def sync_cloud_library(self) -> str:
        workspace = self.user_settings.data
        if not bool(workspace.cloud_enabled):
            return "Cloud sync is disabled in settings."
        root_path = workspace.cloud_root_path.strip()
        if not root_path:
            return "Cloud folder path is empty."
        added = self.library.sync_folder(root_path)
        if added <= 0:
            return "Cloud sync finished. No new library items were added."
        return f"Cloud sync finished. Added or refreshed {added} library items."

    def list_projects(self) -> list[dict[str, str]]:
        return self.projects.list_projects()

    def create_project(self, name: str, brief: str) -> dict[str, object]:
        record = self.projects.create_project(name, brief)
        self.projects.add_memory_entry(record.id, "Project created and waiting for the first Xeno blueprint.")
        return self._serialize_project(self.projects.get_project(record.id)) or {}

    def get_project(self, project_id: str) -> dict[str, object] | None:
        return self._serialize_project(self.projects.get_project(project_id))

    def get_current_project(self) -> dict[str, object] | None:
        return self._serialize_project(self.projects.get_current_project())

    def set_current_project(self, project_id: str) -> dict[str, object] | None:
        return self._serialize_project(self.projects.set_current_project(project_id))

    def update_project_task_status(self, project_id: str, task_title: str, status: str) -> dict[str, object] | None:
        updated = self.projects.update_task_status(project_id, task_title, status)
        if updated is not None:
            self.projects.add_memory_entry(project_id, f"Task updated: {task_title} -> {status.replace('_', ' ')}")
        return self._serialize_project(self.projects.get_project(project_id))

    def _task_dependencies_satisfied(self, project: object, task: dict[str, str]) -> bool:
        dependency_text = str(task.get("dependencies", "")).strip()
        if not dependency_text:
            return True
        dependencies = [item.strip() for item in dependency_text.split("|") if item.strip()]
        if not dependencies:
            return True
        status_by_title = {
            str(item.get("title", "")).strip(): str(item.get("status", "pending")).strip().lower()
            for item in getattr(project, "tasks", [])
            if isinstance(item, dict)
        }
        return all(status_by_title.get(title, "pending") == "completed" for title in dependencies)

    def _task_priority_score(self, task: Mapping[str, object]) -> tuple[int, int, int, str]:
        status = str(task.get("status", "pending")).strip().lower()
        has_hint = bool(str(task.get("action_hint", "")).strip())
        risk = str(task.get("risk", "")).strip().lower()
        tool = str(task.get("tool", "")).strip().lower()
        status_rank = {"in_progress": 0, "pending": 1}.get(status, 2)
        hint_rank = 0 if has_hint else 1
        risk_rank = {"low": 0, "medium": 1, "high": 2}.get(risk, 1)
        tool_rank = {
            "builder": 0,
            "planning": 1,
            "execution": 2,
            "review": 3,
            "observation": 4,
            "memory": 5,
            "architecture": 6,
            "safety": 7,
            "reasoning": 8,
        }.get(tool, 9)
        return (status_rank, hint_rank, risk_rank + tool_rank, str(task.get("title", "")).lower())

    def get_next_agent_task(self, project_id: str) -> dict[str, str] | None:
        project = self.projects.get_project(project_id)
        if project is None:
            return None
        ready: list[dict[str, str]] = []
        blocked: list[dict[str, str]] = []
        for task in project.tasks:
            status = str(task.get("status", "pending")).strip().lower()
            if status == "completed":
                continue
            if self._task_dependencies_satisfied(project, task):
                ready.append(task)
            else:
                blocked.append(task)
        if ready:
            ready.sort(key=self._task_priority_score)
            return ready[0]
        if blocked:
            blocked.sort(key=lambda item: str(item.get("title", "")).lower())
            return blocked[0]
        return None

    def run_next_agent_task(self, project_id: str) -> dict[str, object]:
        next_task = self.get_next_agent_task(project_id)
        if next_task is None:
            return {"ok": False, "message": "No next agent task is available for this project."}
        return self.run_agent_task_action(project_id, next_task)  # type: ignore

    def _agent_loop_task_title(self, task: Mapping[str, object] | None) -> str:
        if not task:
            return "Task"
        return repair_text(str(task.get("title", "Task"))).strip() or "Task"

    def _append_agent_loop_step(
        self,
        loop: AgentLoopResult,
        task: Mapping[str, object] | None,
        result: dict[str, object],
        *,
        repair: bool = False,
    ) -> None:
        title = self._agent_loop_task_title(task)
        status = str(result.get("status", "completed" if result.get("ok") else "failed")).strip() or "completed"
        message = repair_text(str(result.get("message", "")).strip())
        detail = repair_text(str(result.get("detail", "")).strip())
        loop.add_step(
            AgentLoopStep(
                index=len(loop.steps) + 1,
                title=title,
                status=status,
                ok=bool(result.get("ok", False)),
                message=message or detail or title,
                detail=detail,
                repair=repair,
            )
        )
        self._trace_agent(
            phase="agent_loop_repair" if repair else "agent_loop_step",
            status=status,
            detail=detail or message,
            metadata={"task": title, "ok": bool(result.get("ok", False)), "repair": repair},
        )

    def _agent_loop_should_pause_after_success(self, task: Mapping[str, object], result: dict[str, object]) -> bool:
        status = str(result.get("status", "")).strip().lower()
        action_hint = str(task.get("action_hint", "")).strip().lower()
        action_key = str(result.get("action_key", "")).strip().lower()
        if status == "in_progress":
            return True
        if action_hint == "open_workspace_in_tool":
            return True
        return action_key in {"run_command", "run_static_web_server", "open_workspace_in_tool"} and status == "in_progress"

    def _repair_agent_loop_failure(
        self,
        project_id: str,
        task: Mapping[str, object],
        result: dict[str, object],
    ) -> dict[str, object]:
        project = self.projects.get_project(project_id)
        title = self._agent_loop_task_title(task)
        if project is None:
            return {"ok": False, "status": "failed", "message": "Project could not be found for repair."}

        action_hint = str(task.get("action_hint", "")).strip().lower()
        failure_text = ascii_fold_text(
            " ".join(
                [
                    title,
                    action_hint,
                    str(result.get("message", "")),
                    str(result.get("detail", "")),
                ]
            )
        ).lower()
        workspace = self.desktop_actions.ensure_project_workspace(project.name)

        try:
            if "vscode" in failure_text or "vs code" in failure_text or "app path" in failure_text or "cesta" in failure_text:
                repair = self.desktop_actions.describe_app_path("vscode", self.user_settings.data)
                if repair.get("ok"):
                    self.projects.add_memory_entry(project_id, "Agent repair: verified VS Code path before retry.")
                return self._coerce_action_result(repair, category="file_read", title=f"repair: {title}")

            if "workspace" in failure_text or "scaffold" in failure_text or "slozk" in failure_text:
                message = self.desktop_actions.create_project_scaffold(project.name, project.brief)
                self.projects.add_memory_entry(project_id, f"Agent repair: refreshed workspace scaffold for {project.name}.")
                return self._coerce_action_result(message, category="file_change", title=f"repair: {title}")

            if (
                "entrypoint" in failure_text
                or "package.json" in failure_text
                or "spousteci prikaz" in failure_text
                or "run" in failure_text
            ):
                message = self.desktop_actions.create_project_scripts(workspace)
                self.projects.add_memory_entry(project_id, "Agent repair: generated run scripts for the workspace.")
                return self._coerce_action_result(message, category="file_change", title=f"repair: {title}")

            observation = self.desktop_observer.observe(include_screenshot=False)
            summary = self.desktop_observer.summarize(observation)
            self._remember_observation(observation, source="agent loop repair")
            self.projects.add_memory_entry(project_id, f"Agent repair observation: {summary}")
            return {
                "ok": True,
                "status": "completed",
                "message": "Agent checked the desktop state before retry.",
                "detail": summary,
                "category": "observe",
                "action_key": "agent_loop_repair_observe",
                "workspace": str(workspace),
            }
        except OSError as error:
            detail = f"Repair failed: {error}"
            self.projects.add_memory_entry(project_id, f"Agent repair failed: {title} -> {detail}")
            return {"ok": False, "status": "failed", "message": detail, "detail": detail}

    def run_next_agent_chain(self, project_id: str, max_steps: int = 3) -> dict[str, object]:
        self._reload_runtime_preferences()
        max_steps = self._agent_chain_budget(max_steps)
        project = self.projects.get_project(project_id)
        if project is None:
            return {"ok": False, "message": "Project could not be found."}

        preview_tasks: list[dict[str, Any]] = []
        for task in project.tasks:
            status = str(task.get("status", "pending")).strip().lower()
            if status == "completed":
                continue
            preview_tasks.append(task)
            if len(preview_tasks) >= 4:
                break

        intelligence_level = self._normalized_intelligence_level()
        agent_model_support = ""
        if bool(self._runtime_budget_profile()["xeno_model_support"]):
            agent_model_support = self.xeno.task_agent.build_model_execution_support(
                objective=project.brief,
                tasks=preview_tasks,  # type: ignore
                model_generate=self._support_generate,
                intelligence_level=intelligence_level,
            )

        loop = AgentLoopResult()
        self.agent_run_state.start(
            user_input=f"agent loop for {project.name}",
            input_source="agent",
            owner="Luna+Xeno",
            scope="project_agent_loop",
            risk="medium",
            vision_active=bool(self.live_screen_summary or (self.last_desktop_observation or {}).get("vision_summary")),
            xeno_active=bool(agent_model_support),
            status="running",
            note="Autonomous project agent loop started.",
        )
        self._trace_agent(
            phase="agent_loop_start",
            status="running",
            detail=f"Project: {project.name}; max steps: {max_steps}",
            metadata={"project_id": project_id, "max_steps": max_steps},
        )
        last_project = project
        unresolved_failure = False

        for step_number in range(max_steps):
            next_task = self.get_next_agent_task(project_id)
            if next_task is None:
                loop.finish(ok=not unresolved_failure, status="completed", stopped_reason="No more ready tasks.")
                break

            self.agent_run_state.update(
                action_title=self._agent_loop_task_title(next_task),
                tool_name=str(next_task.get("tool", "")),
                status="running",
                note=f"Loop step {step_number + 1}: {self._agent_loop_task_title(next_task)}",
            )
            result = self.run_agent_task_action(project_id, next_task)  # type: ignore
            self._append_agent_loop_step(loop, next_task, result)
            if not result.get("ok"):
                repair = self._repair_agent_loop_failure(project_id, next_task, result)
                self._append_agent_loop_step(loop, next_task, repair, repair=True)
                if repair.get("ok"):
                    retry = self.run_agent_task_action(project_id, next_task)  # type: ignore
                    self._append_agent_loop_step(loop, next_task, retry)
                    if not retry.get("ok"):
                        unresolved_failure = True
                        loop.finish(ok=False, status="failed", stopped_reason="Retry failed after repair.")
                        break
                    result = retry
                else:
                    unresolved_failure = True
                    loop.finish(ok=False, status="failed", stopped_reason="Repair failed.")
                    break

            last_project = self.projects.get_project(project_id) or last_project
            if self._agent_loop_should_pause_after_success(next_task, result):  # type: ignore
                loop.finish(ok=True, status="in_progress", stopped_reason="Started a long-running or user-visible step.")
                break
        else:
            loop.finish(
                ok=not unresolved_failure and loop.executed > 0,
                status="completed" if not unresolved_failure else "failed",
                stopped_reason="Step budget reached.",
            )

        if not loop.stopped_reason:
            if loop.executed == 0 and loop.repaired == 0:
                loop.finish(ok=False, status="failed", stopped_reason="No next agent task could be executed.")
            else:
                loop.finish(
                    ok=not unresolved_failure,
                    status="completed" if not unresolved_failure else "failed",
                    stopped_reason="Loop finished.",
                )

        updated = self.projects.get_project(project_id) or last_project
        final_message = loop.summary()
        self.projects.add_memory_entry(project_id, f"Agent loop: {final_message[:500]}")
        if agent_model_support:
            self.projects.add_memory_entry(project_id, f"Agent model guidance: {agent_model_support[:220]}")
            final_message += "\n\nAgent model guidance:\n" + agent_model_support
        self.agent_run_state.update(
            status=loop.status,
            final_message=final_message,
            note=f"Agent loop stopped: {loop.stopped_reason}",
        )
        self._trace_agent(
            phase="agent_loop_stop",
            status=loop.status,
            detail=loop.stopped_reason,
            metadata={"executed": loop.executed, "repaired": loop.repaired, "failed": loop.failed},
        )
        return {
            "ok": loop.ok,
            "message": final_message,
            "project": self._serialize_project(updated),
            "loop": {
                "status": loop.status,
                "executed": loop.executed,
                "repaired": loop.repaired,
                "failed": loop.failed,
                "stopped_reason": loop.stopped_reason,
            },
        }

    def run_agent_task_action(self, project_id: str, task_payload: dict[str, object] | str) -> dict[str, object]:
        project = self.projects.get_project(project_id)
        if project is None:
            return {"ok": False, "message": "Project could not be found."}

        if isinstance(task_payload, dict):
            task_data = task_payload
            task_title = str(task_payload.get("title", "Task"))
        else:
            task_title = str(task_payload)
            task_data = {"title": task_title}

        task_model_support = ""
        if bool(self._runtime_budget_profile()["xeno_model_support"]):
            task_model_support = self.xeno.task_agent.build_model_execution_support(
                objective=project.brief,
                tasks=[task_data],  # type: ignore
                model_generate=self._support_generate,
                intelligence_level=self._normalized_intelligence_level(),
            )

        action_hint = str(task_data.get("action_hint", "")).strip().lower()
        if action_hint == "observe_desktop_state":
            observation = self.desktop_observer.observe(include_screenshot=False)
            summary = self.desktop_observer.summarize(observation)
            result = {
                "ok": True,
                "status": "completed",
                "message": str(task_data.get("handoff_note", "")).strip() or "Agent observed the active desktop state.",
                "detail": summary,
                "category": "observe",
                "action_key": "observe_desktop_state",
                "workspace": str(self.desktop_actions.ensure_project_workspace(project.name)),
            }
            self._remember_observation(observation, source="agent observe")
        else:
            try:
                result = self.desktop_actions.run_task_action(
                    project_name=project.name,
                    brief=project.brief,
                    next_step=project.next_step,
                    task=task_data,  # type: ignore
                    workspace_settings=self.user_settings.data,
                )
            except OSError as error:
                detail = f"Task action failed: {error}"
                self.projects.add_memory_entry(project_id, f"Agent failed: {task_title} -> {detail}")
                self._log_action("file_change", f"task action: {task_title}", "failed", detail)
                return {"ok": False, "message": detail}

        action_result = self._coerce_action_result(
            result,
            category=str(result.get("category", "file_change")),
            title=f"task action: {task_title}",
        )
        status = str(action_result.get("status", "completed"))
        detail = str(action_result.get("detail", action_result.get("message", ""))).strip()
        category = str(action_result.get("category", "file_change"))
        is_ok = bool(action_result.get("ok", False))

        self.projects.update_task_status(project_id, task_title, status)
        if is_ok:
            self.projects.add_memory_entry(project_id, f"Agent action: {task_title} -> {detail or action_result.get('message', '')}")
        else:
            self.projects.add_memory_entry(project_id, f"Agent failed: {task_title} -> {detail or action_result.get('message', '')}")
        self._log_action(category, f"task action: {task_title}", status, detail or str(action_result.get("message", "")))
        updated = self.projects.get_project(project_id)
        final_message = str(action_result.get("message", "Task agent ran an action."))
        final_detail = detail
        if task_model_support:
            self.projects.add_memory_entry(project_id, f"Agent model guidance: {task_model_support[:220]}")
            final_message = (final_message + "\n\nAgent model guidance:\n" + task_model_support).strip()
            final_detail = (detail + "\n\nAgent model guidance:\n" + task_model_support).strip() if detail else task_model_support
        return {
            "ok": is_ok,
            "message": final_message,
            "detail": final_detail,
            "status": status,
            "workspace": action_result.get("workspace", ""),
            "project": self._serialize_project(updated),
        }

    def open_connected_app(self, app_key: str, project_name: str = "", log_result: bool = True) -> dict[str, str | bool]:
        result = self.desktop_actions.launch_connected_app(
            app_key=app_key,
            workspace_settings=self.user_settings.data,
            project_name=project_name,
        )
        status = "completed" if result.get("ok") else "failed"
        self._log_action("app_launch", f"open {app_key}", status, str(result.get("message", "")))
        return result

    def add_project_memory(self, project_id: str, note: str) -> dict[str, object] | None:
        updated = self.projects.add_memory_entry(project_id, note)
        return self._serialize_project(updated)

    def attach_files_to_project(self, project_id: str, file_paths: list[str]) -> dict[str, object] | None:
        names = [Path(file_path).name for file_path in file_paths if Path(file_path).name]
        self.projects.add_attachment_names(project_id, names)
        if names:
            self.projects.add_memory_entry(project_id, f"New attachments linked: {', '.join(names)}")
        return self._serialize_project(self.projects.get_project(project_id))

    def read_attachment_context(self, file_paths: list[str]) -> str:
        if not file_paths:
            return ""
        analysis = self._analyze_visual_structured(
            file_paths[:4],
            (
                "Read the attached file(s) for LunaAI and Xeno. Extract visible/readable text, "
                "detect errors, summarize important context, and recommend the next safe step."
            ),
        )
        summary = self.vision_layer.summarize(analysis)
        structured = json.dumps(analysis, ensure_ascii=False, indent=2)
        return f"Attached file analysis:\n{summary}\n\nStructured vision/observer JSON:\n{structured}"

    def read_terminal_observation(self, terminal_output: str) -> dict[str, object]:
        return self.observer_layer.read_terminal_output(terminal_output)

    def read_log_observation(self, file_path: str) -> dict[str, object]:
        return self.observer_layer.read_log_file(file_path)

    def read_project_observation(self, root_path: str) -> dict[str, object]:
        return self.observer_layer.read_project_files(root_path)

    def check_process_observation(self, process_names: list[str] | None = None) -> dict[str, object]:
        return self.observer_layer.check_running_processes(process_names)

    def observe_system_state(
        self,
        *,
        project_root: str = "",
        terminal_output: str = "",
        log_files: list[str] | None = None,
        process_names: list[str] | None = None,
    ) -> dict[str, object]:
        return self.observer_layer.observe_system_state(
            project_root=project_root,
            terminal_output=terminal_output,
            log_files=log_files or [],
            process_names=process_names or [],
        )

    def generate_project_package(self, user_input: str, project_name: str = "") -> dict[str, object]:
        intelligence_level = self._normalized_intelligence_level()
        result = self.xeno.project_builder.build_from_request(user_input, intelligence_level=intelligence_level)
        blueprint_text = self.xeno.handle(user_input, intelligence_level=intelligence_level, model_generate=self._support_generate)
        tasks = [
            {
                "title": step.title,
                "status": step.status,
                "description": step.description,
                "tool": step.tool,
                "risk": step.risk,
                "action_hint": step.action_hint,
                "handoff_note": step.handoff_note,
                "dependencies": " | ".join(step.dependencies),
            }
            for step in (result.agent_run.steps if result.agent_run else [])
        ]
        handoff_summary = result.agent_run.handoff_summary if result.agent_run is not None else ""
        xeno_model_support = self.xeno.build_model_support(user_input, self._support_generate, intelligence_level=intelligence_level)
        resolved_name = project_name.strip() or result.blueprint.project_name
        current = self.projects.get_current_project()
        if current is None:
            record = self.projects.create_project(resolved_name, user_input)
        else:
            record = current
        updated = self.projects.update_project(
            record.id,
            name=resolved_name,
            brief=user_input,
            blueprint_text=blueprint_text,
            next_step=result.next_step,
            current_phase=result.agent_run.current_phase if result.agent_run else "planning",
            tasks=tasks,
            handoff_summary=handoff_summary,
        )
        self.projects.add_memory_entry(record.id, f"Xeno refreshed the project plan for {resolved_name}.")
        self.projects.add_memory_entry(record.id, f"Agent next step: {result.next_step}")
        if handoff_summary:
            self.projects.add_memory_entry(record.id, f"Agent handoff: {handoff_summary}")
        if xeno_model_support:
            self.projects.add_memory_entry(record.id, f"Xeno model guidance: {xeno_model_support[:220]}")
        project_id = updated.id if updated is not None else record.id
        return {
            "project_id": project_id,
            "project_name": resolved_name,
            "summary": result.summary,
            "blueprint_text": blueprint_text,
            "next_step": result.next_step,
            "current_phase": result.agent_run.current_phase if result.agent_run else "planning",
            "tasks": tasks,
            "xeno_note": f"Xeno prepared a new execution track for {resolved_name}. {handoff_summary}" + (f"\n\nXeno model guidance:\n{xeno_model_support}" if xeno_model_support else ""),
        }

    def generate_project_blueprint(self, user_input: str) -> str:
        return str(self.generate_project_package(user_input).get("blueprint_text", ""))

    def describe_xeno(self) -> str:
        return self.xeno.describe()

    def clear_history(self) -> None:
        self.memory_coordinator.clear_all()

    def run(self) -> None:
        print("LunaAI launched. Type 'exit' to quit.")
        print("Luna is ready. Just write naturally and it will choose the right style automatically.")
        while True:
            user_input = input("Ty: ").strip()
            if not user_input:
                continue
            response = self.chat(user_input)
            if not response:
                continue
            print(response)
            if user_input.lower() == "exit":
                break



























