from __future__ import annotations

from dataclasses import dataclass

from app.core.text_utils import ascii_fold_text, repair_text


@dataclass(slots=True)
class AgentRoute:
    """One small routing decision shared by chat, voice, vision, Xeno, and actions."""

    user_input: str
    input_source: str
    action_scope: str
    risk: str
    vision_active: bool
    live_visual_query: bool
    action_request: bool
    should_attempt_local_action: bool
    force_auto_execution: bool
    consult_xeno: bool
    summary: str
    reason: str


class AgentActionRouter:
    """Decides how an incoming user turn should move through the agent pipeline.

    This class does not execute actions. It only gives LunaEngine one consistent
    routing decision so typed chat, voice mode, live vision, and Xeno planning do
    not drift into separate behavior paths.
    """

    _DESTRUCTIVE_MARKERS = (
        "delete ",
        "remove ",
        "rm ",
        "rmdir",
        "format ",
        "registry",
        "regedit",
        "smaz",
        "vymaz",
        "odstran",
    )

    _VISUAL_QUERY_MARKERS = (
        "co vidis",
        "co vidiš",
        "co je na obrazovce",
        "popis obrazovku",
        "popis mi obrazek",
        "popis mi obrázek",
        "rekni mi co vidis",
        "řekni mi co vidíš",
        "what do you see",
        "describe the screen",
        "describe image",
        "describe picture",
    )

    _ACTION_MARKERS = (
        "otevri",
        "otevři",
        "open",
        "spust",
        "spusť",
        "chrom",
        "zapni",
        "launch",
        "start",
        "jdi na",
        "go to",
        "dej",
        "hod",
        "vyhledej",
        "search",
        "najdi",
        "vytvor",
        "vytvoř",
        "udelej",
        "udělej",
        "create",
        "make",
        "precti",
        "přečti",
        "vypis",
        "list folder",
        "read file",
        "klikni",
        "click",
        "stiskni",
        "press",
        "napis text",
        "napiš text",
        "type text",
        "run project",
        "spust projekt",
    )

    _SAFE_VOICE_AUTO_MARKERS = (
        "otevri",
        "otevři",
        "open",
        "spust",
        "spusť",
        "chrom",
        "zapni",
        "launch",
        "start",
        "jdi na",
        "dej",
        "hod",
        "vyhledej",
        "search",
        "najdi na webu",
        "go to",
    )

    _SYSTEM_INPUT_MARKERS = (
        "klikni",
        "click",
        "stiskni",
        "press",
        "shortcut",
        "klaves",
        "kláves",
        "napis text",
        "napiš text",
        "type text",
        "do aktivniho okna",
        "do aktivního okna",
    )

    _FILE_CHANGE_MARKERS = (
        "vytvor",
        "vytvoř",
        "udelej",
        "udělej",
        "create",
        "make",
        "prepis",
        "přepiš",
        "rewrite",
        "overwrite",
        "append",
        "pridej do",
        "přidej do",
    )

    def route(
        self,
        user_input: str,
        *,
        extra_context: str = "",
        current_action_mode: str = "ask",
        xeno_consulted: bool = False,
    ) -> AgentRoute:
        clean_input = repair_text(str(user_input or "")).strip()
        clean_context = repair_text(str(extra_context or ""))
        normalized = ascii_fold_text(f"{clean_input} {clean_context}").lower()
        normalized_input = ascii_fold_text(clean_input).lower()

        input_source = "voice" if "input source: voice" in normalized or "voice mode:" in normalized else "chat"
        vision_active = (
            "active desktop share:" in normalized
            or "newest shared frame" in normalized
            or "current live vision summary" in normalized
            or "vision summary:" in normalized
            or "attached file:" in normalized
        )
        live_visual_query = vision_active and any(marker in normalized_input for marker in self._VISUAL_QUERY_MARKERS)
        destructive = any(marker in normalized_input for marker in self._DESTRUCTIVE_MARKERS)
        action_request = any(marker in normalized_input for marker in self._ACTION_MARKERS)
        system_input = any(marker in normalized_input for marker in self._SYSTEM_INPUT_MARKERS)
        file_change = any(marker in normalized_input for marker in self._FILE_CHANGE_MARKERS)

        safe_voice_auto = (
            input_source == "voice"
            and action_request
            and not destructive
            and not system_input
            and not file_change
            and any(marker in normalized_input for marker in self._SAFE_VOICE_AUTO_MARKERS)
        )

        should_attempt_local_action = action_request and not destructive and not live_visual_query
        action_scope = self._action_scope(
            action_request=action_request,
            live_visual_query=live_visual_query,
            vision_active=vision_active,
            system_input=system_input,
            file_change=file_change,
            destructive=destructive,
        )
        risk = self._risk(
            destructive=destructive,
            system_input=system_input,
            file_change=file_change,
            action_request=action_request,
        )
        force_auto_execution = safe_voice_auto and current_action_mode != "block"
        consult_xeno = bool(xeno_consulted or action_request or destructive or (vision_active and action_request))

        reason = self._reason(
            input_source=input_source,
            action_scope=action_scope,
            force_auto_execution=force_auto_execution,
            vision_active=vision_active,
            live_visual_query=live_visual_query,
        )
        summary = self._summary(
            input_source=input_source,
            action_scope=action_scope,
            risk=risk,
            vision_active=vision_active,
            live_visual_query=live_visual_query,
            should_attempt_local_action=should_attempt_local_action,
            force_auto_execution=force_auto_execution,
            consult_xeno=consult_xeno,
            reason=reason,
        )

        return AgentRoute(
            user_input=clean_input,
            input_source=input_source,
            action_scope=action_scope,
            risk=risk,
            vision_active=vision_active,
            live_visual_query=live_visual_query,
            action_request=action_request,
            should_attempt_local_action=should_attempt_local_action,
            force_auto_execution=force_auto_execution,
            consult_xeno=consult_xeno,
            summary=summary,
            reason=reason,
        )

    def _action_scope(
        self,
        *,
        action_request: bool,
        live_visual_query: bool,
        vision_active: bool,
        system_input: bool,
        file_change: bool,
        destructive: bool,
    ) -> str:
        if destructive:
            return "blocked_risk"
        if live_visual_query:
            return "live_vision_answer"
        if system_input:
            return "system_input"
        if file_change:
            return "file_or_project_change"
        if action_request:
            return "local_action"
        if vision_active:
            return "vision_context_chat"
        return "conversation"

    def _risk(
        self,
        *,
        destructive: bool,
        system_input: bool,
        file_change: bool,
        action_request: bool,
    ) -> str:
        if destructive:
            return "high"
        if system_input or file_change:
            return "medium"
        if action_request:
            return "low"
        return "none"

    def _reason(
        self,
        *,
        input_source: str,
        action_scope: str,
        force_auto_execution: bool,
        vision_active: bool,
        live_visual_query: bool,
    ) -> str:
        if force_auto_execution:
            return "Voice command is a reversible open/search/start action, so it can run through auto mode."
        if action_scope == "system_input":
            return "System input can affect the active external window, so it stays behind confirmation."
        if action_scope == "file_or_project_change":
            return "File/project changes are allowed but should stay visible and verified."
        if action_scope == "blocked_risk":
            return "The request looks destructive or system-risky and must not run automatically."
        if live_visual_query:
            return "The user is asking about visual context, so the newest screenshot or attachment is the source of truth."
        if vision_active:
            return "Vision context is active, so the answer should be grounded in the newest visual source."
        if input_source == "voice":
            return "Voice mode is active, so keep the flow short and action-oriented."
        return "Normal chat route."

    def _summary(
        self,
        *,
        input_source: str,
        action_scope: str,
        risk: str,
        vision_active: bool,
        live_visual_query: bool,
        should_attempt_local_action: bool,
        force_auto_execution: bool,
        consult_xeno: bool,
        reason: str,
    ) -> str:
        lines = [
            "Unified agent route:",
            f"- Source: {input_source}",
            f"- Scope: {action_scope}",
            f"- Risk: {risk}",
            f"- Vision active: {'yes' if vision_active else 'no'}",
            f"- Visual query: {'yes' if live_visual_query else 'no'}",
            f"- Try local action: {'yes' if should_attempt_local_action else 'no'}",
            f"- Voice auto-execute: {'yes' if force_auto_execution else 'no'}",
            f"- Xeno check: {'yes' if consult_xeno else 'no'}",
            f"- Reason: {reason}",
        ]
        return "\n".join(lines)
