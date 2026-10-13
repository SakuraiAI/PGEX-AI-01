from __future__ import annotations

from dataclasses import dataclass, field

from app.core.presence_layer import PresenceLayer, PresenceState


@dataclass(slots=True)
class AgentContextBundle:
    instruction: str
    hidden_support: str
    session_context: str
    include_history: bool
    coordination: dict[str, object]
    active_layers: list[str] = field(default_factory=list)


class AgentOrchestrator:
    """Connects Luna, Xeno, Vision, Voice, memory, and actions into one prompt flow."""

    def __init__(self) -> None:
        self.presence = PresenceLayer()

    def build(
        self,
        *,
        user_input: str,
        base_instruction: str,
        response_author: str,
        xeno_consulted: bool,
        coordination: dict[str, object],
        hidden_xeno_support: str = "",
        automation_summary: str = "",
        extra_context: str = "",
        observer_context: str = "",
        session_context: str = "",
        live_visual_query: bool = False,
        voice_mode: bool = False,
    ) -> AgentContextBundle:
        active_layers = self._active_layers(
            xeno_consulted=xeno_consulted,
            extra_context=extra_context,
            observer_context=observer_context,
            automation_summary=automation_summary,
            voice_mode=voice_mode,
        )
        presence_state = PresenceState(
            response_author=response_author,
            active_layers=active_layers,
            voice_mode=voice_mode,
            live_visual_query=live_visual_query,
        )
        instruction = self._instruction(
            base_instruction=base_instruction,
            voice_mode=voice_mode,
            active_layers=active_layers,
            presence_state=presence_state,
        )
        hidden_support = self._hidden_support(
            user_input=user_input,
            response_author=response_author,
            active_layers=active_layers,
            presence_state=presence_state,
            hidden_xeno_support=hidden_xeno_support,
            automation_summary=automation_summary,
            extra_context=extra_context,
            observer_context=observer_context,
            coordination=coordination,
        )
        session_context = self._session_context(
            session_context=session_context,
            live_visual_query=live_visual_query,
            voice_mode=voice_mode,
            has_vision="Vision" in active_layers,
        )

        return AgentContextBundle(
            instruction=instruction,
            hidden_support=hidden_support,
            session_context=session_context,
            include_history=not live_visual_query,
            coordination=coordination,
            active_layers=active_layers,
        )

    def _active_layers(
        self,
        *,
        xeno_consulted: bool,
        extra_context: str,
        observer_context: str,
        automation_summary: str,
        voice_mode: bool,
    ) -> list[str]:
        layers = ["Luna"]
        if xeno_consulted:
            layers.append("Xeno")
        if (
            "Active desktop share:" in extra_context
            or "Current live vision summary" in extra_context
            or "Vision summary:" in extra_context
            or "Attached file:" in extra_context
        ):
            layers.append("Vision")
        if observer_context:
            layers.append("Desktop observer")
        if automation_summary:
            layers.append("Action planner")
        if voice_mode:
            layers.append("Voice")
        return layers

    def _instruction(
        self,
        *,
        base_instruction: str,
        voice_mode: bool,
        active_layers: list[str],
        presence_state: PresenceState,
    ) -> str:
        parts = [base_instruction.strip()] if base_instruction.strip() else []
        parts.append(
            "Luna Core Loop is active: combine user input, visual context, memory, Xeno support, and safe actions into one final answer."
        )
        parts.append(
            "Do not mention internal layers unless the user asks. Use them silently to be more useful."
        )
        parts.append(self.presence.build_instruction(presence_state))
        if voice_mode:
            parts.append(
                "Voice mode: answer like spoken conversation. Use short natural sentences, no markdown tables, no long lists, "
                "no code blocks unless absolutely needed, and keep the first sentence emotionally present and direct."
            )
        if "Vision" in active_layers:
            parts.append(
                "Vision is active: prefer the newest attached file, screenshot, or explicit vision summary over older screen descriptions."
            )
        if "Action planner" in active_layers:
            parts.append(
                "Action planner is active: separate what you can say from what the action layer actually did or still needs confirmation for."
            )
        return " ".join(part for part in parts if part)

    def _hidden_support(
        self,
        *,
        user_input: str,
        response_author: str,
        active_layers: list[str],
        presence_state: PresenceState,
        hidden_xeno_support: str,
        automation_summary: str,
        extra_context: str,
        observer_context: str,
        coordination: dict[str, object],
    ) -> str:
        sections = [
            "Luna Core Loop context:",
            f"- Final speaker: {response_author or 'Luna'}",
            f"- Active layers: {', '.join(active_layers)}",
            f"- User intent: {user_input}",
        ]
        sections.append("\n" + self.presence.build_state_note(presence_state))

        coordination_text = self._coordination_text(coordination)
        if coordination_text:
            sections.append("\nInternal coordination:\n" + coordination_text)
        if hidden_xeno_support:
            sections.append("\nHidden Xeno support:\n" + hidden_xeno_support.strip())
        if automation_summary:
            sections.append("\nAction planner support:\n" + automation_summary.strip())
        if observer_context:
            sections.append("\nDesktop observer context:\n" + observer_context.strip())
        if extra_context:
            sections.append("\nLive/attachment context:\n" + extra_context.strip())
        return "\n".join(section for section in sections if str(section).strip())

    def _coordination_text(self, coordination: dict[str, object]) -> str:
        tracks = coordination.get("tracks", [])
        if not isinstance(tracks, list):
            return ""
        lines: list[str] = []
        for item in tracks:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker", "")).strip()
            note = str(item.get("note", "")).strip()
            if speaker and note:
                lines.append(f"{speaker}: {note}")
        return "\n".join(lines)

    def _session_context(
        self,
        *,
        session_context: str,
        live_visual_query: bool,
        voice_mode: bool,
        has_vision: bool,
    ) -> str:
        lines = [session_context.strip()] if session_context.strip() else []
        if has_vision:
            lines.append(
                "Visual freshness rule: visual summaries are temporary. Prefer the newest screenshot, document, or attachment over older chat history."
            )
        if live_visual_query:
            lines.append(
                "Visual query rule: ignore older screen descriptions from this chat. "
                "Use only the newest screenshot, attachment, or vision summary. "
                "If the newest visual source is unclear, say it is unclear."
            )
        if voice_mode:
            lines.append(
                "Voice delivery rule: this answer may be spoken aloud, so keep it clean, warm, short, and free of markdown clutter."
            )
        return "\n".join(line for line in lines if line)
