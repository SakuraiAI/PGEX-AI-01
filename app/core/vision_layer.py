from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.text_utils import clean_model_response_text, sanitize_text_for_transport
from app.models.nvidia_vision_model import NvidiaVisionModel


ERROR_PATTERN = re.compile(
    r"(?im)\b("
    r"error|exception|traceback|failed|failure|cannot|can't|invalid|denied|"
    r"attributeerror|typeerror|valueerror|syntaxerror|importerror|modulenotfounderror|"
    r"unicode(?:decode|encode)error|pylance|npm err|vite error|http\s*[45]\d\d"
    r")\b.*"
)


class VisionLayer:
    """One-shot visual and document understanding.

    This layer does not stream the desktop and does not control the mouse. It
    only converts explicit inputs such as screenshots, images, videos, and
    readable documents into structured context for Luna, Xeno, and Agent.
    """

    READABLE_DOCUMENT_EXTENSIONS = {
        ".txt",
        ".md",
        ".markdown",
        ".py",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".csv",
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
        ".sql",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".java",
        ".rs",
        ".go",
        ".php",
        ".rb",
        ".lua",
    }

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}

    def __init__(self, vision_model: NvidiaVisionModel) -> None:
        self.vision_model = vision_model

    def analyze(self, file_paths: list[str], query: str = "", source: str = "") -> dict[str, Any]:
        paths = [Path(item) for item in file_paths if str(item or "").strip()]
        if not paths:
            return self._empty_analysis(source or "unknown", "No input files were provided.")

        detected_text_parts: list[str] = []
        detected_errors: list[str] = []
        important_parts: list[str] = []
        model_outputs: list[str] = []
        readable_files: list[str] = []
        media_files: list[str] = []
        unsupported_files: list[str] = []
        analysis_errors: list[str] = []
        media_analyzed = False

        for path in paths:
            if not path.is_file():
                analysis_errors.append(f"File not found or not a regular file: {path}")
                continue

            suffix = path.suffix.lower()
            if suffix in self.READABLE_DOCUMENT_EXTENSIONS:
                text = self._read_text_file(path)
                if text:
                    readable_files.append(str(path))
                    detected_text_parts.append(f"{path.name}:\n{text[:6000]}")
                    detected_errors.extend(self.detect_errors(text))
                else:
                    analysis_errors.append(f"{path.name} is empty or unreadable as text.")
                continue

            if self.vision_model.supports_path(path):
                media_files.append(str(path))
                continue

            unsupported_files.append(str(path))
            analysis_errors.append(f"Unsupported file format: {path.name}")

        if media_files:
            try:
                model_text = self._analyze_media_with_model(media_files, query=query)
            except Exception as error:
                analysis_errors.append(f"Vision analysis failed: {error}")
                model_text = ""
            if model_text:
                model_outputs.append(model_text)
                parsed = self._parse_model_json(model_text)
                if parsed is not None:
                    detected_text_parts.append(str(parsed.get("detected_text", "") or "").strip())
                    detected_errors.extend(self._as_string_list(parsed.get("detected_errors")))
                    important_parts.append(str(parsed.get("important_context", "") or "").strip())
                    media_analyzed = bool(
                        str(parsed.get("detected_text", "") or "").strip()
                        or self._as_string_list(parsed.get("detected_errors"))
                        or str(parsed.get("important_context", "") or "").strip()
                    )
                else:
                    media_analyzed = True
                    detected_text_parts.append(model_text)
                    detected_errors.extend(self.detect_errors(model_text))

            if not media_analyzed and not analysis_errors:
                analysis_errors.append("Vision model returned no useful analysis.")

        source_type = source.strip() or self._infer_source_type(paths, media_files, readable_files)
        detected_text = self._join_clean(detected_text_parts, limit=12000)
        detected_errors = self._dedupe(detected_errors)
        important_context = self._join_clean(important_parts, limit=4000)
        if not important_context:
            important_context = self._build_context_summary(
                source_type=source_type,
                detected_text=detected_text,
                detected_errors=detected_errors,
                readable_files=readable_files,
                media_files=media_files,
                unsupported_files=unsupported_files,
            )

        confidence = self._estimate_confidence(
            detected_text=detected_text,
            detected_errors=detected_errors,
            media_files=media_files,
            readable_files=readable_files,
            unsupported_files=unsupported_files,
        )

        success = bool(readable_files or media_analyzed)
        return {
            "ok": success,
            "analysis_errors": self._dedupe(analysis_errors),
            "type": "screen_analysis" if source_type in {"screenshot", "image", "video"} else "document_analysis",
            "source": source_type,
            "detected_text": detected_text,
            "detected_errors": detected_errors,
            "important_context": important_context,
            "confidence": confidence if success else 0.0,
            "recommended_next_step": (
                self._recommended_next_step(detected_errors, source_type) if success
                else "Resolve the input or model errors and retry the analysis."
            ),
            "files": [str(path) for path in paths],
            "readable_files": readable_files,
            "media_files": media_files,
            "unsupported_files": unsupported_files,
            "raw_model_output": "\n\n".join(model_outputs).strip(),
        }

    def analyze_screenshot(self, file_path: str, query: str = "") -> dict[str, Any]:
        return self.analyze([file_path], query=query, source="screenshot")

    def read_document(self, file_path: str, query: str = "") -> dict[str, Any]:
        del query
        return self.analyze([file_path], source="document")

    def detect_errors(self, text: str) -> list[str]:
        clean = sanitize_text_for_transport(text)
        matches = [match.group(0).strip() for match in ERROR_PATTERN.finditer(clean)]
        return self._dedupe(matches)[:20]

    def summarize(self, analysis: dict[str, Any]) -> str:
        source = str(analysis.get("source", "input") or "input")
        context = str(analysis.get("important_context", "") or "").strip()
        text = str(analysis.get("detected_text", "") or "").strip()
        errors = self._as_string_list(analysis.get("detected_errors"))
        next_step = str(analysis.get("recommended_next_step", "") or "").strip()

        parts = [f"Vision analysis ({source}):"]
        if context:
            parts.append(context)
        elif text:
            parts.append(text[:900])
        if errors:
            parts.append("Detected errors:\n- " + "\n- ".join(errors[:6]))
        analysis_errors = self._as_string_list(analysis.get("analysis_errors"))
        if analysis_errors:
            parts.append("Analysis errors:\n- " + "\n- ".join(analysis_errors[:6]))
        if next_step:
            parts.append(f"Recommended next step: {next_step}")
        return "\n".join(parts).strip()

    def _analyze_media_with_model(self, media_files: list[str], query: str = "") -> str:
        if not self.vision_model.is_available():
            raise RuntimeError("Vision model is not configured or available.")

        prompt = (
            "Analyze the provided screenshot/image/video for LunaAI. Return only JSON with this exact shape: "
            '{"type":"screen_analysis","source":"screenshot|image|video","detected_text":"...",'
            '"detected_errors":[],"important_context":"...","confidence":0.0,'
            '"recommended_next_step":"..."}. '
            "Do not invent actions, hidden windows, files, or successful commands. "
            "If text is visible, extract it. If errors are visible, list them. "
            "User query: "
            + (query.strip() or "Understand the current visual state.")
        )
        return self.vision_model.analyze_media(query=prompt, media_files=media_files[:4])

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "cp1250", "cp1252", "latin-1"):
            try:
                return sanitize_text_for_transport(path.read_text(encoding=encoding, errors="strict")).strip()
            except OSError:
                return ""
            except UnicodeError:
                continue
        return ""

    def _parse_model_json(self, value: str) -> dict[str, Any] | None:
        text = clean_model_response_text(value).strip()
        candidates = [text]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _infer_source_type(self, paths: list[Path], media_files: list[str], readable_files: list[str]) -> str:
        if media_files:
            suffixes = {Path(path).suffix.lower() for path in media_files}
            if suffixes & self.VIDEO_EXTENSIONS:
                return "video"
            names = " ".join(Path(path).name.lower() for path in media_files)
            if "screenshot" in names or "snimek" in names or "desktop" in names or "screen" in names:
                return "screenshot"
            return "image"
        if readable_files:
            return "document"
        if paths:
            return paths[0].suffix.lower().lstrip(".") or "file"
        return "unknown"

    def _build_context_summary(
        self,
        *,
        source_type: str,
        detected_text: str,
        detected_errors: list[str],
        readable_files: list[str],
        media_files: list[str],
        unsupported_files: list[str],
    ) -> str:
        if detected_errors:
            return f"{source_type} contains visible or textual errors that should be handled before continuing."
        if detected_text:
            return f"{source_type} contains readable context that can ground Luna, Xeno, and Agent."
        if media_files:
            return f"{source_type} media was provided, but no useful text was extracted."
        if readable_files:
            return "Readable document files were provided but no content was extracted."
        if unsupported_files:
            return "Some files are unsupported for direct vision/document reading without an additional parser."
        return "No important visual or document context was detected."

    def _recommended_next_step(self, detected_errors: list[str], source_type: str) -> str:
        if detected_errors:
            return "Route the detected errors to Xeno for diagnosis, then let Agent apply only safe fixes."
        if source_type in {"screenshot", "image", "video"}:
            return "Use this visual context to answer the user or plan the next safe action."
        if source_type == "document":
            return "Summarize the document and extract actionable requirements for Luna/Xeno."
        return "Ask for a clearer file, screenshot, or log if the context is not enough."

    def _estimate_confidence(
        self,
        *,
        detected_text: str,
        detected_errors: list[str],
        media_files: list[str],
        readable_files: list[str],
        unsupported_files: list[str],
    ) -> float:
        confidence = 0.25
        if detected_text:
            confidence += 0.35
        if detected_errors:
            confidence += 0.15
        if media_files and self.vision_model.is_available():
            confidence += 0.2
        if readable_files:
            confidence += 0.15
        if unsupported_files:
            confidence -= 0.15
        return max(0.05, min(0.95, round(confidence, 2)))

    def _empty_analysis(self, source: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "type": "screen_analysis",
            "source": source,
            "detected_text": "",
            "detected_errors": [],
            "important_context": message,
            "confidence": 0.0,
            "recommended_next_step": "Provide a screenshot, document, log, or readable file.",
            "files": [],
        }

    def _join_clean(self, parts: list[str], limit: int) -> str:
        clean_parts = [sanitize_text_for_transport(part).strip() for part in parts if str(part or "").strip()]
        return "\n\n".join(clean_parts).strip()[:limit]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = " ".join(sanitize_text_for_transport(item).split())
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
