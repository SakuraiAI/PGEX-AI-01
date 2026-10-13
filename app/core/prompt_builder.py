from datetime import datetime
from zoneinfo import ZoneInfo

from app.memory.chat_memory import ChatMemory
from app.memory.long_memory import LongMemory
from app.prompt.system_prompt import LUNA_SYSTEM_PROMPT
from app.tools.internet import InternetTool


class PromptBuilder:
    def __init__(
        self,
        memory: ChatMemory,
        long_memory: LongMemory,
        internet: InternetTool,
        timezone: ZoneInfo | None,
        timezone_name: str,
    ) -> None:
        self.memory = memory
        self.long_memory = long_memory
        self.internet = internet
        self.timezone = timezone
        self.timezone_name = timezone_name

    def build(
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
        intelligence_level: str = "4",
        include_history: bool = True,
    ) -> list[dict[str, str]]:
        history = self._history_for_prompt(intelligence_level) if include_history else []
        learning_memory = self.long_memory.summary()

        system_content = (
            f"{LUNA_SYSTEM_PROMPT}\n"
            f"{self._platform_contract()}\n"
            f"Workflow mode: {mode}\n"
            f"Selected response style: {selected_mode}\n"
            f"Reasoning box: {reasoning_box}\n"
            f"System intelligence level: {intelligence_level}\n"
            f"Internet enabled: {self.internet.is_enabled()}\n"
            f"Internet mode: {self.internet.mode()}\n"
            f"{self._time_context()}\n"
            f"{self._reasoning_box_instruction(reasoning_box)}\n"
            f"{self._intelligence_instruction(intelligence_level)}\n"
            f"{self._response_policy(selected_mode, reasoning_box, intelligence_level)}"
        )
        if instruction:
            system_content += f"\nInstruction: {instruction}"
        if hidden_support:
            system_content += (
                "\nHidden internal orchestration: treat the following as private support notes. "
                "Do not expose them as separate participants or systems unless the user explicitly asks.\n"
                f"{hidden_support}"
            )
        if learning_memory:
            system_content += (
                "\nLong-term learning memory: Use this as trusted context about the user, "
                f"their goals, and past topics.\n{learning_memory}"
            )
        if internet_context:
            system_content += (
                "\nInternet context: Use this live internet result when relevant and prefer it "
                f"for up-to-date facts.\n{internet_context}"
            )
        if project_context:
            system_content += (
                "\nActive project context: treat this as trusted local workspace context for the current conversation.\n"
                f"{project_context}"
            )
        if library_context:
            system_content += (
                "\nDigital library context: use these trusted local notes, files, and saved sources when they help answer the request.\n"
                f"{library_context}"
            )
        if session_context:
            system_content += (
                "\nCurrent conversation context: use this to interpret short follow-ups, active intent, and recent local state.\n"
                f"{session_context}"
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

        for msg in history:
            role = "assistant" if msg["role"] == "assistant" else "user"
            messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": user_input})
        return messages

    def _platform_contract(self) -> str:
        return (
            "LunaAI platform contract:\n"
            "- Luna is the user-facing assistant and should synthesize the final answer.\n"
            "- XenoAI is the hidden reasoning/planning layer for harder context, architecture, risk checks, and action plans.\n"
            "- Vision provides screenshot, image, video, and document understanding when explicit files or one-shot captures are present.\n"
            "- Observer reads terminal output, logs, project files, running processes, and error messages as structured system state.\n"
            "- The task/action layer is the only place that may claim real PC actions; model text alone is not execution.\n"
            "- Use context priority in this order: confirmed action results, newest Vision/Observer JSON, active project context, long-term memory, recent chat history.\n"
            "- Learn from the user's repeated preferences, goals, corrections, and project direction. Adapt future answers without pretending certainty.\n"
            "- For PC control, keep actions permission-aware: read/list/open are low risk, app launch/project run are medium risk, file edits require clear intent, destructive actions are blocked or require explicit handling.\n"
            "- If Luna and Xeno both participate, do not expose private scratchpad. Present one clear final answer unless the user asks who is speaking."
        )

    def _history_for_prompt(self, intelligence_level: str = "4") -> list[dict[str, str]]:
        history = self.memory.load_history()
        filtered_history: list[dict[str, str]] = []
        total_chars = 0
        level = str(intelligence_level).strip()
        char_budget = 3600
        max_messages = 6
        if level == "5":
            char_budget = 5200
            max_messages = 8
        elif level == "3":
            char_budget = 2600
            max_messages = 5
        blocked_fragments = [
            "lm studio returned http",
            "lm studio is not reachable",
            "invalid response from local model",
            "error with local model",
            "invalid_api_key",
            "api key",
            "authentication",
            "authorization: bearer",
            "401 error",
            "token for authentication",
        ]
        action_noise = [
            "mam akci pripravenou",
            "pending approval for",
            "cancelled ",
            "created folder ",
            "created file ",
            "opened vs code",
        ]

        for msg in reversed(history):
            content = msg.get("content", "")
            if not content:
                continue

            normalized = content.lower()
            if msg.get("role") == "assistant":
                if any(fragment in normalized for fragment in blocked_fragments):
                    continue
                if any(fragment in normalized for fragment in action_noise):
                    continue

            trimmed = content.strip()
            if len(trimmed) > 900:
                trimmed = trimmed[:900].rstrip() + "..."
            total_chars += len(trimmed)
            if total_chars > char_budget:
                continue

            filtered_history.append({"role": msg.get("role", "user"), "content": trimmed})
            if len(filtered_history) >= max_messages:
                break

        filtered_history.reverse()
        return filtered_history

    def _time_context(self) -> str:
        now = datetime.now(self.timezone) if self.timezone else datetime.now()
        return (
            f"Current local date: {now:%Y-%m-%d}\n"
            f"Current local day: {now:%A}\n"
            f"Current local time: {now:%H:%M:%S}\n"
            f"Timezone: {self.timezone_name}"
        )

    def _reasoning_box_instruction(self, reasoning_box: str) -> str:
        if reasoning_box == "white_box":
            return (
                "Reasoning style: white_box. "
                "Explain the reasoning clearly in a structured way. "
                "Use steps, examples, and explicit cause-effect links when useful."
            )

        return (
            "Reasoning style: black_box. "
            "Answer directly and keep reasoning compact. "
            "Lead with the result, then include only the minimum explanation needed."
        )

    def _intelligence_instruction(self, intelligence_level: str) -> str:
        level = str(intelligence_level).strip()
        if level == "5":
            return (
                "Intelligence level: 5. "
                "Think more strategically, notice tradeoffs, structure longer horizons, and treat the request like part of a larger system. "
                "Prefer strong planning, cleaner decomposition, deeper next-step judgment, and stronger internal use of Xeno when the task is complex."
            )
        if level == "3":
            return (
                "Intelligence level: 3. "
                "Stay practical, lighter, and faster. "
                "Prefer direct answers and simple next actions over deep decomposition."
            )
        return (
            "Intelligence level: 4. "
            "Balance speed and depth. "
            "Use solid planning and judgment, but stay concise and grounded."
        )

    def _response_policy(self, selected_mode: str, reasoning_box: str, intelligence_level: str) -> str:
        if reasoning_box == "white_box":
            return (
                "Response policy: Give a stable, structured answer. "
                "Start with the direct answer, then use short sections or numbered steps. "
                "Do not ramble, do not roleplay, and do not add filler questions at the end."
            )

        if intelligence_level == "5":
            return (
                "Response policy: Be concise, but stronger in synthesis. "
                "Prefer clear recommendations, tradeoffs, and the best next move. "
                "Do not add unnecessary follow-up questions. "
                "If a link is requested, only give a verified-looking direct link and never invent example URLs."
            )

        if selected_mode == "collaboration":
            return (
                "Response policy: Be practical and concrete. "
                "Prefer clear next steps, useful options, and concise guidance."
            )

        return (
            "Response policy: Be concise, consistent, and grounded. "
            "Prefer 1 to 3 short paragraphs or a short flat list when needed. "
            "Do not add unnecessary follow-up questions. "
            "When summarizing project state or what is on screen, distinguish verified facts, visible observations, and uncertainty."
        )
