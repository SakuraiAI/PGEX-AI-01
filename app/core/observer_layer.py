from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.core.text_utils import sanitize_text_for_transport
from app.core.vision_layer import ERROR_PATTERN


class ObserverLayer:
    """System state reader for LunaAI.

    Observer does not move the mouse, type, or control remote desktop. It only
    reads explicit system inputs: terminal output, logs, project files, and
    process lists. The output is structured so Xeno can reason and Agent can
    decide safe next steps.
    """

    READABLE_EXTENSIONS = {
        ".txt",
        ".md",
        ".py",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".log",
        ".ini",
        ".toml",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".css",
        ".xml",
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
        ".env",
    }

    IGNORED_DIRS = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
    }

    def read_terminal_output(self, output: str) -> dict[str, Any]:
        text = sanitize_text_for_transport(output)
        errors = self.detect_errors(text)
        return self._analysis(
            source="terminal",
            detected_text=text[-12000:],
            detected_errors=errors,
            important_context=self._terminal_context(text, errors),
        )

    def read_log_file(self, file_path: str, max_chars: int = 16000) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            return self._analysis(
                source="log",
                detected_text="",
                detected_errors=[f"Log file not found: {path}"],
                important_context="The requested log file does not exist.",
                confidence=0.1,
            )
        text = self._read_text_file(path)
        tail = text[-max_chars:]
        errors = self.detect_errors(tail)
        return self._analysis(
            source="log",
            detected_text=tail,
            detected_errors=errors,
            important_context=f"Read log file {path.name}. " + self._error_context(errors),
            files=[str(path)],
        )

    def read_project_files(self, root_path: str, max_files: int = 80, max_chars_per_file: int = 2500) -> dict[str, Any]:
        root = Path(root_path or ".").resolve()
        if not root.exists() or not root.is_dir():
            return self._analysis(
                source="project_files",
                detected_text="",
                detected_errors=[f"Project folder not found: {root}"],
                important_context="The requested project folder does not exist or is not a directory.",
                confidence=0.1,
            )

        file_summaries: list[str] = []
        files: list[str] = []
        errors: list[str] = []
        for path in self._iter_project_files(root, max_files=max_files):
            files.append(str(path))
            if path.suffix.lower() not in self.READABLE_EXTENSIONS:
                file_summaries.append(f"{path.relative_to(root)} [binary or skipped]")
                continue
            text = self._read_text_file(path)
            local_errors = self.detect_errors(text)
            errors.extend(local_errors)
            snippet = text[:max_chars_per_file].strip()
            file_summaries.append(f"{path.relative_to(root)}\n{snippet}" if snippet else f"{path.relative_to(root)} [empty]")

        return self._analysis(
            source="project_files",
            detected_text="\n\n---\n\n".join(file_summaries)[:18000],
            detected_errors=self._dedupe(errors),
            important_context=f"Scanned {len(files)} files under {root}. " + self._error_context(errors),
            files=files,
        )

    def check_running_processes(self, process_names: list[str] | None = None) -> dict[str, Any]:
        requested = [self._normalize_process_name(name) for name in (process_names or []) if str(name or "").strip()]
        processes = self._read_process_list()
        if requested:
            matched = [
                item for item in processes
                if self._normalize_process_name(str(item.get("name", ""))) in requested
            ]
        else:
            interesting = {"code.exe", "blender.exe", "unrealeditor.exe", "chrome.exe", "python.exe", "node.exe", "electron.exe"}
            matched = [item for item in processes if self._normalize_process_name(str(item.get("name", ""))) in interesting]

        text = "\n".join(f"{item.get('name')} pid={item.get('pid')}" for item in matched)
        return self._analysis(
            source="processes",
            detected_text=text,
            detected_errors=[],
            important_context=f"Detected {len(matched)} relevant running processes.",
            confidence=0.85 if processes else 0.25,
            running_processes=matched,
        )

    def observe_system_state(
        self,
        *,
        project_root: str = "",
        terminal_output: str = "",
        log_files: list[str] | None = None,
        process_names: list[str] | None = None,
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        if terminal_output.strip():
            parts.append(self.read_terminal_output(terminal_output))
        for log_file in log_files or []:
            parts.append(self.read_log_file(log_file))
        if project_root.strip():
            parts.append(self.read_project_files(project_root))
        parts.append(self.check_running_processes(process_names))

        detected_text = "\n\n".join(str(part.get("detected_text", "")) for part in parts if part.get("detected_text"))
        detected_errors = self._dedupe([
            error
            for part in parts
            for error in self._as_string_list(part.get("detected_errors"))
        ])
        context = "\n".join(str(part.get("important_context", "")) for part in parts if part.get("important_context"))
        confidence = max((float(part.get("confidence", 0.0) or 0.0) for part in parts), default=0.0)

        return self._analysis(
            source="system_state",
            detected_text=detected_text[:20000],
            detected_errors=detected_errors,
            important_context=context or "System state was read without notable context.",
            confidence=confidence,
            observations=parts,
        )

    def detect_errors(self, text: str) -> list[str]:
        clean = sanitize_text_for_transport(text)
        return self._dedupe(match.group(0).strip() for match in ERROR_PATTERN.finditer(clean))[:30]

    def _iter_project_files(self, root: Path, max_files: int) -> list[Path]:
        files: list[Path] = []
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in self.IGNORED_DIRS]
            for file_name in file_names:
                files.append(Path(current_root) / file_name)
                if len(files) >= max_files:
                    return files
        return files

    def _read_process_list(self) -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        try:
            completed = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []

        items: list[dict[str, Any]] = []
        for line in (completed.stdout or "").splitlines():
            columns = self._parse_tasklist_csv_line(line)
            if len(columns) < 2:
                continue
            items.append({"name": columns[0], "pid": columns[1]})
        return items

    def _parse_tasklist_csv_line(self, line: str) -> list[str]:
        # tasklist CSV is simple quoted CSV; avoid importing csv for this tiny hot path.
        columns: list[str] = []
        current = ""
        in_quotes = False
        index = 0
        while index < len(line):
            char = line[index]
            if char == '"':
                in_quotes = not in_quotes
            elif char == "," and not in_quotes:
                columns.append(current)
                current = ""
            else:
                current += char
            index += 1
        columns.append(current)
        return [item.strip().strip('"') for item in columns]

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "cp1250", "cp1252", "latin-1"):
            try:
                return sanitize_text_for_transport(path.read_text(encoding=encoding, errors="strict")).strip()
            except OSError:
                return ""
            except UnicodeError:
                continue
        return ""

    def _terminal_context(self, text: str, errors: list[str]) -> str:
        if errors:
            return "Terminal output contains errors that should be diagnosed before the next action."
        if re.search(r"(?im)\b(done|success|built|compiled|listening|ready)\b", text):
            return "Terminal output looks successful or ready."
        return "Terminal output was read and can be used as current system context."

    def _error_context(self, errors: list[str]) -> str:
        if errors:
            return "Errors were detected and should be routed to Xeno before Agent changes files."
        return "No obvious errors were detected."

    def _analysis(
        self,
        *,
        source: str,
        detected_text: str,
        detected_errors: list[str],
        important_context: str,
        confidence: float | None = None,
        files: list[str] | None = None,
        running_processes: list[dict[str, Any]] | None = None,
        observations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        errors = self._dedupe(detected_errors)
        score = confidence if confidence is not None else self._estimate_confidence(detected_text, errors)
        result: dict[str, Any] = {
            "ok": bool(detected_text or important_context or errors),
            "type": "system_observation",
            "source": source,
            "detected_text": sanitize_text_for_transport(detected_text).strip(),
            "detected_errors": errors,
            "important_context": sanitize_text_for_transport(important_context).strip(),
            "confidence": max(0.0, min(0.95, round(float(score), 2))),
            "recommended_next_step": self._recommended_next_step(errors, source),
        }
        if files is not None:
            result["files"] = files
        if running_processes is not None:
            result["running_processes"] = running_processes
        if observations is not None:
            result["observations"] = observations
        return result

    def _recommended_next_step(self, errors: list[str], source: str) -> str:
        if errors:
            return "Ask Xeno to diagnose the detected errors and produce a safe fix plan."
        if source == "project_files":
            return "Use the file context to plan implementation or code review."
        if source == "processes":
            return "Use process state to verify whether the expected app is running."
        return "Use this observer context to ground the next Luna response."

    def _estimate_confidence(self, detected_text: str, errors: list[str]) -> float:
        confidence = 0.35
        if detected_text:
            confidence += 0.35
        if errors:
            confidence += 0.15
        return confidence

    def _normalize_process_name(self, value: str) -> str:
        text = value.strip().lower()
        if text and not text.endswith(".exe") and "." not in text:
            text += ".exe"
        return text

    def _dedupe(self, items: list[str] | Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = " ".join(sanitize_text_for_transport(str(item or "")).split())
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)
            result.append(clean)
        return result

    def _as_string_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []
