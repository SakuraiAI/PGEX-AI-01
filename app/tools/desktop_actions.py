from __future__ import annotations

import os
import ctypes
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote_plus

from app.core.user_settings import UserWorkspaceSettings
from app.tools.app_discovery import find_registered_app, launch_registered_app


@dataclass(slots=True)
class ActionResult:
    ok: bool
    status: str
    message: str
    detail: str = ""
    category: str = "system"
    action_key: str = ""
    workspace: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


class DesktopActionTool:
    APP_PATH_FIELDS = {
        "unreal": "unreal_engine_path",
        "blender": "blender_path",
        "fl_studio": "fl_studio_path",
        "photoshop": "photoshop_path",
        "vscode": "vscode_path",
        "chrome": "chrome_path",
        "davinci": "davinci_resolve_path",
        "unity": "unity_path",
        "premiere": "premiere_pro_path",
        "after_effects": "after_effects_path",
        "figma": "figma_path",
        "substance": "substance_painter_path",
    }

    APP_DISPLAY_NAMES = {
        "unreal": "Unreal Engine 5",
        "blender": "Blender",
        "fl_studio": "FL Studio",
        "photoshop": "Photoshop",
        "vscode": "VS Code",
        "chrome": "Google Chrome",
        "davinci": "DaVinci Resolve",
        "unity": "Unity",
        "premiere": "Premiere Pro",
        "after_effects": "After Effects",
        "figma": "Figma",
        "substance": "Substance 3D Painter",
    }

    ACTION_HINT_REGISTRY = {
        "create_scope_file": {"category": "file_change", "label": "Create scope file"},
        "create_execution_plan": {"category": "file_change", "label": "Create execution plan"},
        "create_project_scaffold": {"category": "file_change", "label": "Create project scaffold"},
        "open_workspace_in_tool": {"category": "app_launch", "label": "Open workspace in tool"},
        "run_project": {"category": "project_run", "label": "Run project"},
        "refresh_review_notes": {"category": "file_change", "label": "Refresh review notes"},
        "observe_desktop_state": {"category": "observe", "label": "Observe desktop state"},
        "type_text": {"category": "system_input", "label": "Type text into active window"},
        "press_shortcut": {"category": "system_input", "label": "Press keyboard shortcut"},
        "mouse_click": {"category": "system_input", "label": "Click screen coordinates"},
    }

    KEYBOARD_KEY_CODES = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "pause": 0x13,
        "capslock": 0x14,
        "escape": 0x1B,
        "esc": 0x1B,
        "space": 0x20,
        "pageup": 0x21,
        "pagedown": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "insert": 0x2D,
        "delete": 0x2E,
        "win": 0x5B,
        "windows": 0x5B,
    }

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path("data/projects/workspaces")
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def _result(
        self,
        *,
        ok: bool,
        status: str,
        message: str,
        detail: str = "",
        category: str = "system",
        action_key: str = "",
        workspace: str = "",
    ) -> dict[str, str | bool]:
        return ActionResult(
            ok=ok,
            status=status,
            message=message.strip(),
            detail=detail.strip(),
            category=category,
            action_key=action_key,
            workspace=workspace,
        ).to_dict()

    def _require_windows_input(self) -> None:
        if os.name != "nt":
            raise OSError("System input automation is currently supported only on Windows.")

    def _virtual_key_for(self, key_name: str) -> int:
        cleaned = str(key_name or "").strip().lower().replace(" ", "")
        if not cleaned:
            raise OSError("Missing key name.")
        if cleaned in self.KEYBOARD_KEY_CODES:
            return self.KEYBOARD_KEY_CODES[cleaned]
        if re.fullmatch(r"f(?:[1-9]|1[0-2])", cleaned):
            return 0x70 + int(cleaned[1:]) - 1
        if len(cleaned) == 1 and cleaned.isalnum():
            return ord(cleaned.upper())
        raise OSError(f"Unsupported key: {key_name}")

    def _key_event(self, virtual_key: int, *, key_up: bool = False) -> None:
        self._require_windows_input()
        flags = 0x0002 if key_up else 0
        ctypes.windll.user32.keybd_event(virtual_key, 0, flags, 0)

    def _unicode_key_event(self, char: str, *, key_up: bool = False) -> None:
        self._require_windows_input()
        if not char:
            return
        codepoint = ord(char)
        if codepoint > 0xFFFF:
            return

        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUTUNION)]

        flags = 0x0004 | (0x0002 if key_up else 0)
        event = INPUT(type=1, union=INPUTUNION(ki=KEYBDINPUT(0, codepoint, flags, 0, ULONG_PTR(0))))
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
        if sent != 1:
            raise OSError("Windows did not accept the keyboard input event.")

    def list_registered_actions(self) -> list[dict[str, str]]:
        return [
            {"action_key": key, "category": value["category"], "label": value["label"]}
            for key, value in self.ACTION_HINT_REGISTRY.items()
        ]

    def describe_action_hint(self, action_hint: str) -> dict[str, str]:
        return dict(self.ACTION_HINT_REGISTRY.get(action_hint, {"category": "system", "label": action_hint or "Manual action"}))

    def _slugify(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
        normalized = normalized.strip("-")
        return normalized or "project"

    def get_project_workspace(self, project_name: str) -> Path:
        return self.workspace_root / self._slugify(project_name)

    def ensure_project_workspace(self, project_name: str) -> Path:
        workspace = self.get_project_workspace(project_name)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def create_project_scaffold(self, project_name: str, brief: str = "") -> Path:
        workspace = self.ensure_project_workspace(project_name)
        for folder in ["docs", "src", "assets", "references"]:
            (workspace / folder).mkdir(parents=True, exist_ok=True)

        readme = workspace / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {project_name}\n\n{brief.strip() or 'Project created by Luna and the task agent.'}\n",
                encoding="utf-8",
            )

        notes = workspace / "docs" / "execution_notes.md"
        if not notes.exists():
            notes.write_text(
                "# Execution Notes\n\n- Initial scaffold created by Luna's task agent.\n",
                encoding="utf-8",
            )

        return workspace

    def create_execution_plan_file(self, project_name: str, next_step: str) -> Path:
        workspace = self.ensure_project_workspace(project_name)
        plan_file = workspace / "docs" / "execution_plan.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(
            f"# Execution Plan\n\n## Next step\n\n{next_step.strip() or 'Define the next milestone.'}\n",
            encoding="utf-8",
        )
        return plan_file

    def create_scope_file(self, project_name: str, brief: str) -> Path:
        workspace = self.ensure_project_workspace(project_name)
        brief_file = workspace / "docs" / "project_scope.md"
        brief_file.parent.mkdir(parents=True, exist_ok=True)
        brief_file.write_text(
            f"# Project Scope\n\n{brief.strip() or 'Scope to be refined with Luna.'}\n",
            encoding="utf-8",
        )
        return brief_file

    def create_folder(self, path: Path) -> str:
        resolved = Path(path).expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        return f"Created folder {resolved}"

    def create_folders_batch(self, targets: list[Path]) -> str:
        created: list[str] = []
        existing: list[str] = []

        for path in targets:
            resolved = Path(path).expanduser()
            if resolved.exists():
                existing.append(str(resolved))
            else:
                resolved.mkdir(parents=True, exist_ok=True)
                created.append(str(resolved))

        parts: list[str] = []
        if created:
            parts.append(f"Created {len(created)} folders: {', '.join(created)}")
        if existing:
            parts.append(f"{len(existing)} folders already existed: {', '.join(existing)}")
        if not parts:
            return "No folders were created."
        return ". ".join(parts) + "."

    def create_file(self, path: Path, content: str = "") -> str:
        resolved = Path(path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if resolved.exists():
            return f"File already exists: {resolved}"
        resolved.write_text(content, encoding="utf-8")
        return f"Created file {resolved}"

    def overwrite_file(self, path: Path, content: str) -> str:
        resolved = Path(path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Updated file {resolved}"

    def append_to_file(self, path: Path, content: str) -> str:
        resolved = Path(path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if resolved.exists():
            existing = resolved.read_text(encoding="utf-8", errors="ignore")
            prefix = "" if existing.endswith("\n") or not existing else "\n"
        else:
            prefix = ""
        with resolved.open("a", encoding="utf-8") as handle:
            handle.write(prefix + content)
        return f"Appended content to {resolved}"

    def create_files_batch(self, targets: dict[Path, str]) -> str:
        created: list[str] = []
        updated: list[str] = []

        for path, content in targets.items():
            resolved = Path(path).expanduser()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            existed = resolved.exists()
            resolved.write_text(content, encoding="utf-8")
            if existed:
                updated.append(str(resolved))
            else:
                created.append(str(resolved))

        parts: list[str] = []
        if created:
            parts.append(f"Created {len(created)} files")
        if updated:
            parts.append(f"updated {len(updated)} files")
        if not parts:
            return "No files were created."
        return " and ".join(parts) + "."

    def create_python_project(self, project_name: str) -> Path:
        workspace = self.ensure_project_workspace(project_name)
        self.create_folder(workspace / "src")
        self.create_folder(workspace / "tests")
        self.create_files_batch(
            {
                workspace / "main.py": (
                    'def main() -> None:\n'
                    '    print("Hello from LunaAI")\n\n\n'
                    'if __name__ == "__main__":\n'
                    '    main()\n'
                ),
                workspace / "requirements.txt": "",
                workspace / "README.md": f"# {project_name}\n\nPython project scaffold created by Luna.\n",
                workspace / "src" / "__init__.py": "",
                workspace / "tests" / "test_smoke.py": "def test_smoke() -> None:\n    assert True\n",
            }
        )
        return workspace

    def create_python_calculator(self, workspace: Path) -> str:
        target_workspace = Path(workspace).expanduser()
        self.create_folder(target_workspace / "src")
        main_file = target_workspace / "src" / "main.py"
        init_file = target_workspace / "src" / "__init__.py"
        readme_file = target_workspace / "README.md"

        calculator_code = '''from __future__ import annotations


def add(left: float, right: float) -> float:
    return left + right


def subtract(left: float, right: float) -> float:
    return left - right


def multiply(left: float, right: float) -> float:
    return left * right


def divide(left: float, right: float) -> float:
    if right == 0:
        raise ValueError("Division by zero is not allowed.")
    return left / right


OPERATIONS = {
    "+": add,
    "-": subtract,
    "*": multiply,
    "/": divide,
}


def read_number(label: str) -> float:
    while True:
        raw_value = input(f"{label}: ").strip().replace(",", ".")
        try:
            return float(raw_value)
        except ValueError:
            print("Please enter a valid number.")


def read_operation() -> str:
    while True:
        operation = input("Operation (+, -, *, /): ").strip()
        if operation in OPERATIONS:
            return operation
        print("Choose one of: +, -, *, /")


def run_calculator() -> None:
    print("LunaAI Calculator")
    print("Type Ctrl+C to exit.\\n")

    while True:
        left = read_number("First number")
        operation = read_operation()
        right = read_number("Second number")

        try:
            result = OPERATIONS[operation](left, right)
        except ValueError as error:
            print(f"Error: {error}\\n")
            continue

        print(f"Result: {left:g} {operation} {right:g} = {result:g}\\n")


if __name__ == "__main__":
    run_calculator()
'''

        files = {
            main_file: calculator_code,
            init_file: "",
        }
        if not readme_file.exists():
            files[readme_file] = (
                "# Calculator\n\n"
                "Small Python calculator created by LunaAI.\n\n"
                "Run it with:\n\n"
                "```bash\n"
                "python src/main.py\n"
                "```\n"
            )

        message = self.create_files_batch(files)
        return f"{message} Calculator code is ready in {main_file}."

    def create_project_scripts(self, workspace: Path) -> str:
        target_workspace = Path(workspace).expanduser()
        scripts_folder = target_workspace / "scripts"
        self.create_folder(scripts_folder)

        init_script = r'''@echo off
setlocal
cd /d "%~dp0.."

echo Preparing LunaAI project workspace...
if not exist src mkdir src
if not exist docs mkdir docs
if not exist tests mkdir tests
if not exist scripts mkdir scripts

if not exist .venv (
  python -m venv .venv
)

call .venv\Scripts\activate.bat
if exist requirements.txt (
  python -m pip install -r requirements.txt
) else (
  echo No requirements.txt found. Skipping dependency install.
)

echo Workspace is ready.
pause
'''
        run_project_script = r'''@echo off
setlocal
cd /d "%~dp0.."

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)

if exist package.json (
  where npm >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    npm run dev
    pause
    exit /b
  )
)

if exist src\main.py (
  python -u src\main.py
) else if exist main.py (
  python -u main.py
) else if exist app.py (
  python -u app.py
) else (
  echo No runnable entrypoint found. Expected package.json, src\main.py, main.py, or app.py.
)

pause
'''
        run_calculator_script = r'''@echo off
setlocal
cd /d "%~dp0.."

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)

if exist src\main.py (
  python -u src\main.py
) else (
  echo Calculator entrypoint not found: src\main.py
)

pause
'''
        run_tests_script = r'''@echo off
setlocal
cd /d "%~dp0.."

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)

if exist tests (
  python -m pytest tests
) else (
  echo Tests folder does not exist yet.
)

pause
'''

        files = {
            scripts_folder / "init_workspace.bat": init_script,
            scripts_folder / "run_project.bat": run_project_script,
            scripts_folder / "run_calc.bat": run_calculator_script,
            scripts_folder / "run_tests.bat": run_tests_script,
        }
        message = self.create_files_batch(files)
        return f"{message} Project scripts are ready in {scripts_folder}."

    def create_simple_web_page(self, workspace: Path, description: str = "") -> str:
        target_workspace = Path(workspace).expanduser()
        web_folder = target_workspace / "web"
        self.create_folder(web_folder)

        lowered_description = description.lower()
        title = "LunaAI Web"
        headline = "A clean web page built with LunaAI"
        subheadline = "Small, readable, and ready to customize."
        if "portfolio" in lowered_description:
            title = "Portfolio"
            headline = "Portfolio"
            subheadline = "A focused place for projects, skills, and contact."
        elif "landing" in lowered_description:
            title = "Landing Page"
            headline = "Launch your idea"
            subheadline = "A simple landing page with a clear call to action."

        index_html = f'''<!doctype html>
<html lang="cs">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="page-shell">
    <section class="hero">
      <p class="eyebrow">Created with LunaAI</p>
      <h1>{headline}</h1>
      <p class="lead">{subheadline}</p>
      <div class="actions">
        <a href="#projects" class="button primary">View projects</a>
        <a href="#contact" class="button secondary">Contact</a>
      </div>
    </section>

    <section id="projects" class="cards" aria-label="Project highlights">
      <article class="card">
        <span>01</span>
        <h2>Structure</h2>
        <p>HTML keeps the content clear and easy to edit.</p>
      </article>
      <article class="card">
        <span>02</span>
        <h2>Style</h2>
        <p>CSS gives the page a dark, polished visual direction.</p>
      </article>
      <article class="card">
        <span>03</span>
        <h2>Motion</h2>
        <p>JavaScript adds a small status line when the page loads.</p>
      </article>
    </section>

    <section id="contact" class="contact">
      <h2>Ready to build the next section?</h2>
      <p id="status">Page loaded.</p>
    </section>
  </main>
  <script src="script.js"></script>
</body>
</html>
'''
        styles_css = '''* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  font-family: "Trebuchet MS", "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at 20% 10%, rgba(255, 255, 255, 0.14), transparent 26rem),
    linear-gradient(135deg, #101010 0%, #181512 48%, #0b0b0b 100%);
  color: #f6f1e8;
}

.page-shell {
  width: min(1120px, calc(100% - 32px));
  margin: 0 auto;
  padding: 72px 0;
}

.hero {
  min-height: 62vh;
  display: grid;
  align-content: center;
}

.eyebrow {
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #d8b86a;
  font-weight: 700;
}

h1 {
  margin: 0;
  max-width: 820px;
  font-size: clamp(3rem, 9vw, 7rem);
  line-height: 0.92;
}

.lead {
  max-width: 620px;
  color: #cfc7b7;
  font-size: 1.25rem;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 22px;
}

.button {
  border-radius: 999px;
  padding: 14px 20px;
  text-decoration: none;
  font-weight: 800;
}

.primary {
  background: #f6f1e8;
  color: #111;
}

.secondary {
  border: 1px solid rgba(246, 241, 232, 0.28);
  color: #f6f1e8;
}

.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.card,
.contact {
  border: 1px solid rgba(246, 241, 232, 0.12);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.06);
  padding: 24px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.26);
}

.card span {
  color: #d8b86a;
  font-weight: 900;
}

.contact {
  margin-top: 16px;
}

@media (max-width: 760px) {
  .cards {
    grid-template-columns: 1fr;
  }
}
'''
        script_js = '''const statusLine = document.querySelector("#status");

if (statusLine) {
  const time = new Date().toLocaleTimeString();
  statusLine.textContent = `Page ready at ${time}.`;
}
'''
        readme = '''# Web Page

This folder contains a small static web page created by LunaAI.

Files:
- `index.html` keeps the page content and layout.
- `styles.css` controls the visual design.
- `script.js` adds a tiny interactive status update.

Open `index.html` in a browser to preview it.
'''

        files = {
            web_folder / "index.html": index_html,
            web_folder / "styles.css": styles_css,
            web_folder / "script.js": script_js,
            web_folder / "README.md": readme,
        }
        message = self.create_files_batch(files)
        return f"{message} Web page is ready in {web_folder}."

    def create_email_draft(
        self,
        workspace: Path,
        *,
        recipient: str = "",
        subject: str = "",
        body: str = "",
    ) -> str:
        target_workspace = Path(workspace).expanduser()
        drafts_folder = target_workspace / "drafts"
        self.create_folder(drafts_folder)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        draft_file = drafts_folder / f"email_{timestamp}.md"
        cleaned_recipient = recipient.strip() or "TODO: doplnit prijemce"
        cleaned_subject = subject.strip() or "TODO: doplnit predmet"
        cleaned_body = body.strip() or "TODO: doplnit text zpravy"
        draft = (
            "# Email Draft\n\n"
            "Status: not sent\n"
            f"To: {cleaned_recipient}\n"
            f"Subject: {cleaned_subject}\n\n"
            "## Body\n\n"
            f"{cleaned_body}\n\n"
            "---\n"
            "Safety note: LunaAI only prepared this draft. It did not send the email.\n"
        )
        self.create_file(draft_file, draft)
        return f"Email draft is ready in {draft_file}. Nothing was sent."

    def create_web_project(self, project_name: str) -> Path:
        workspace = self.ensure_project_workspace(project_name)
        self.create_folder(workspace / "assets")
        self.create_files_batch(
            {
                workspace / "index.html": (
                    "<!doctype html>\n"
                    '<html lang="en">\n'
                    "<head>\n"
                    '  <meta charset="UTF-8">\n'
                    '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                    "  <title>Luna Web Project</title>\n"
                    '  <link rel="stylesheet" href="styles.css">\n'
                    "</head>\n"
                    "<body>\n"
                    "  <main>\n"
                    "    <h1>Hello from LunaAI</h1>\n"
                    "    <p>Your web project is ready.</p>\n"
                    "  </main>\n"
                    '  <script src="script.js"></script>\n'
                    "</body>\n"
                    "</html>\n"
                ),
                workspace / "styles.css": (
                    "body {\n"
                    "  font-family: Arial, sans-serif;\n"
                    "  background: #111;\n"
                    "  color: #f5f5f5;\n"
                    "  margin: 0;\n"
                    "  min-height: 100vh;\n"
                    "  display: grid;\n"
                    "  place-items: center;\n"
                    "}\n"
                ),
                workspace / "script.js": "console.log('Luna web project ready');\n",
                workspace / "README.md": f"# {project_name}\n\nWeb project scaffold created by Luna.\n",
            }
        )
        return workspace



    def create_electron_project(self, project_name: str) -> Path:
        workspace = self.ensure_project_workspace(project_name)
        self.create_folder(workspace / "electron")
        self.create_folder(workspace / "src")
        self.create_folder(workspace / "src" / "components")
        self.create_files_batch(
            {
                workspace / "package.json": (
                    "{\n"
                    f'  "name": "{self._slugify(project_name)}",\n'
                    '  "version": "0.1.0",\n'
                    '  "private": true,\n'
                    '  "main": "electron/main.js",\n'
                    '  "scripts": {\n'
                    '    "dev": "electron ."\n'
                    '  }\n'
                    "}\n"
                ),
                workspace / "electron" / "main.js": (
                    "const { app, BrowserWindow } = require('electron');\n\n"
                    "function createWindow() {\n"
                    "  const win = new BrowserWindow({ width: 1200, height: 800 });\n"
                    "  win.loadFile('index.html');\n"
                    "}\n\n"
                    "app.whenReady().then(createWindow);\n"
                ),
                workspace / "index.html": (
                    "<!doctype html>\n"
                    '<html lang="en">\n'
                    '<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>LunaAI Desktop</title></head>\n'
                    '<body><div id="app">Hello from LunaAI Electron</div><script type="module" src="src/main.js"></script></body>\n'
                    "</html>\n"
                ),
                workspace / "src" / "main.js": "console.log('Luna Electron project ready');\n",
                workspace / "README.md": f"# {project_name}\n\nElectron desktop project scaffold created by Luna.\n",
            }
        )
        return workspace

    def open_path(self, path: Path) -> str:
        resolved = Path(path).expanduser()
        os.startfile(str(resolved))
        return f"Opened {resolved}"

    def list_folder(self, path: Path, limit: int = 80) -> str:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise OSError(f"Folder does not exist: {resolved}")
        if not resolved.is_dir():
            raise OSError(f"Expected a folder, got file: {resolved}")

        entries = sorted(
            resolved.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        visible_entries = entries[: max(1, limit)]
        lines = [f"Obsah slozky {resolved}:"]
        for item in visible_entries:
            marker = "[DIR]" if item.is_dir() else "[FILE]"
            lines.append(f"- {marker} {item.name}")
        remaining = len(entries) - len(visible_entries)
        if remaining > 0:
            lines.append(f"... a jeste {remaining} dalsich polozek.")
        if not visible_entries:
            lines.append("- slozka je prazdna")
        return "\n".join(lines)

    def read_text_file(self, path: Path, max_chars: int = 12000) -> str:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise OSError(f"File does not exist: {resolved}")
        if not resolved.is_file():
            raise OSError(f"Expected a file, got folder: {resolved}")

        size = resolved.stat().st_size
        if size > 2_000_000:
            raise OSError(f"File is too large to read safely: {resolved} ({size} bytes)")

        content = resolved.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars].rstrip()

        suffix = "\n\n... soubor je zkraceny, protoze je dlouhy." if truncated else ""
        return f"Soubor {resolved}:\n\n{content}{suffix}"

    def find_paths(
        self,
        roots: list[Path],
        query: str,
        *,
        prefer_directory: bool | None = None,
        max_results: int = 20,
        max_scanned: int = 8000,
    ) -> str:
        cleaned_query = str(query or "").strip().strip('"').strip("'").lower()
        if not cleaned_query:
            raise OSError("Missing file or folder search query.")

        results: list[Path] = []
        scanned = 0
        seen_roots: set[str] = set()
        for root in roots:
            resolved_root = Path(root).expanduser().resolve()
            root_key = str(resolved_root).lower()
            if root_key in seen_roots or not resolved_root.exists() or not resolved_root.is_dir():
                continue
            seen_roots.add(root_key)
            for current_root, dir_names, file_names in os.walk(resolved_root):
                scanned += 1
                if scanned > max_scanned or len(results) >= max_results:
                    break
                names = dir_names if prefer_directory is True else file_names if prefer_directory is False else [*dir_names, *file_names]
                for name in names:
                    if cleaned_query in name.lower():
                        candidate = Path(current_root) / name
                        if prefer_directory is True and not candidate.is_dir():
                            continue
                        if prefer_directory is False and not candidate.is_file():
                            continue
                        results.append(candidate)
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
            if scanned > max_scanned or len(results) >= max_results:
                break

        if not results:
            return f"Nenasla jsem nic pro `{query}` v omezenem rozsahu hledani."

        lines = [f"Nasla jsem {len(results)} vysledku pro `{query}`:"]
        for path in results:
            marker = "[DIR]" if path.is_dir() else "[FILE]"
            lines.append(f"- {marker} {path}")
        if scanned > max_scanned:
            lines.append("Hledani jsem zastavila na bezpecnem limitu, aby se neprochazel cely disk.")
        return "\n".join(lines)

    def _chrome_candidates(self) -> list[Path]:
        candidates: list[Path] = []

        settings_file = Path("data/settings/user_settings.json")
        try:
            settings_payload = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings_payload = {}
        if isinstance(settings_payload, dict):
            configured = str(settings_payload.get("chrome_path", "") or "").strip()
            if configured:
                candidates.append(Path(configured).expanduser())

        apps_config = self._load_apps_config()
        configured = str(apps_config.get("chrome", "") or "").strip()
        if configured:
            candidates.append(Path(configured).expanduser())

        roots = [
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            "C:/Program Files",
            "C:/Program Files (x86)",
        ]
        for root in roots:
            if not root:
                continue
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
        found_on_path = shutil.which("chrome") or shutil.which("chrome.exe")
        if found_on_path:
            candidates.append(Path(found_on_path))
        return candidates

    def _find_chrome_path(self) -> Path | None:
        for candidate in self._chrome_candidates():
            if candidate.exists():
                return candidate
        return None

    def _decode_process_output(self, output: bytes | str | None) -> str:
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        if output.startswith((b"\xff\xfe", b"\xfe\xff")):
            return output.decode("utf-16", errors="ignore")
        for encoding in ("utf-8", "cp1250", "mbcs"):
            try:
                return output.decode(encoding, errors="ignore")
            except LookupError:
                continue
        return output.decode(errors="ignore")

    def _is_process_running(self, process_names: set[str]) -> bool:
        if os.name != "nt":
            return False
        expected = {name.strip().lower() for name in process_names if name.strip()}
        if not expected:
            return False
        for process_name in expected:
            try:
                completed = subprocess.run(
                    ["tasklist.exe", "/FI", f"IMAGENAME eq {process_name}"],
                    capture_output=True,
                    text=False,
                    timeout=3,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            output = self._decode_process_output(completed.stdout).lower()
            if completed.returncode == 0 and process_name in output:
                return True
        return False

    def _normalize_url(self, value: str) -> str:
        url = str(value or "").strip()
        if not url:
            raise OSError("Missing URL.")
        if url.lower().startswith("localhost:"):
            return f"http://{url}"
        if url.lower().startswith("www."):
            return f"https://{url}"
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            return f"https://{url}"
        return url

    def _process_name_for_pid(self, process_id: int) -> str:
        if os.name != "nt" or not process_id:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(process_id))
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            if not ok:
                return ""
            return Path(buffer.value).name
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def _focus_window_by_process_names(self, process_names: set[str], *, timeout_seconds: float = 2.5) -> bool:
        if os.name != "nt":
            return False

        expected = {name.strip().lower() for name in process_names if name.strip()}
        if not expected:
            return False

        user32 = ctypes.windll.user32
        end_at = time.time() + max(0.2, timeout_seconds)
        SW_RESTORE = 9

        while time.time() < end_at:
            matches: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def enum_proc(hwnd: int, _lparam: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process_name = self._process_name_for_pid(int(pid.value)).lower()
                if process_name in expected:
                    matches.append(int(hwnd))
                return True

            user32.EnumWindows(enum_proc, 0)

            for hwnd in matches:
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.BringWindowToTop(hwnd)
                if user32.SetForegroundWindow(hwnd):
                    return True
                if int(user32.GetForegroundWindow()) == hwnd:
                    return True

            time.sleep(0.15)

        return False

    def open_url(self, url: str, *, prefer_chrome: bool = False) -> dict[str, str | bool]:
        normalized_url = self._normalize_url(url)
        expected_domain = (
            normalized_url.lower()
            .removeprefix("https://")
            .removeprefix("http://")
            .split("/", 1)[0]
            .removeprefix("www.")
        )
        chrome_path = self._find_chrome_path() if prefer_chrome else None
        if chrome_path is not None:
            subprocess.Popen([str(chrome_path), normalized_url])
            focused = self._focus_window_by_process_names({"chrome.exe"}, timeout_seconds=3.0)
            running = self._is_process_running({"chrome.exe"})
            expected_app = "browser"
        else:
            os.startfile(normalized_url)
            focused = self._focus_window_by_process_names(
                {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe"},
                timeout_seconds=3.0,
            )
            running = self._is_process_running({"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe"})
            expected_app = "browser"

        if not focused and not running:
            return self._result(
                ok=False,
                status="failed",
                message=f"Požádala jsem o otevření {normalized_url}, ale nepotvrdila jsem běžící okno prohlížeče.",
                detail=f"URL launch requested: {normalized_url}. No browser process/window was confirmed.",
                category="app_launch",
                action_key="open_url",
            )

        focus_detail = "Browser window focused." if focused else "Browser process is running, but foreground focus was not confirmed."
        result = self._result(
            ok=True,
            status="completed",
            message=f"Otevřela jsem {normalized_url}.",
            detail=f"URL opened: {normalized_url}. {focus_detail}",
            category="app_launch",
            action_key="open_url",
        )
        result["target_url"] = normalized_url
        result["target_domain"] = expected_domain
        result["expected_app_key"] = expected_app
        result["focus_confirmed"] = focused
        result["process_confirmed"] = running
        result["message"] = (
            f"Otevřela jsem {normalized_url}."
            if focused
            else f"Otevřela jsem {normalized_url}, ale nepodařilo se mi potvrdit, že je okno nahoře."
        )
        return result

    def search_web(self, query: str, *, prefer_chrome: bool = False) -> dict[str, str | bool]:
        cleaned_query = str(query or "").strip()
        if not cleaned_query:
            return self._result(
                ok=False,
                status="failed",
                message="Chybi hledany dotaz.",
                detail="No search query was provided.",
                category="app_launch",
                action_key="search_web",
            )
        url = f"https://www.google.com/search?q={quote_plus(cleaned_query)}"
        result = self.open_url(url, prefer_chrome=prefer_chrome)
        result["message"] = f"Hledám na webu: {cleaned_query}"
        result["action_key"] = "search_web"
        result["search_query"] = cleaned_query
        return result

    def open_browser(self, *, prefer_chrome: bool = True) -> dict[str, str | bool]:
        result = self.open_url("https://www.google.com", prefer_chrome=prefer_chrome)
        result["action_key"] = "open_browser"
        if bool(result.get("ok")):
            result["message"] = (
                "Otevřela jsem Google Chrome."
                if bool(result.get("focus_confirmed"))
                else "Google Chrome běží, ale nepodařilo se mi potvrdit, že je okno nahoře."
            )
        result["target_domain"] = ""
        return result

    def press_shortcut(self, shortcut: str) -> dict[str, str | bool]:
        self._require_windows_input()
        parts = [part.strip() for part in re.split(r"\+|\s+", str(shortcut or "")) if part.strip()]
        if not parts:
            raise OSError("Missing shortcut.")
        if len(parts) > 4:
            raise OSError("Shortcut is too long for safe automation.")

        keys = [self._virtual_key_for(part) for part in parts]
        for key in keys:
            self._key_event(key, key_up=False)
            time.sleep(0.025)
        for key in reversed(keys):
            self._key_event(key, key_up=True)
            time.sleep(0.025)

        return self._result(
            ok=True,
            status="completed",
            message=f"Stiskla jsem zkratku {shortcut}.",
            detail=f"Keyboard shortcut pressed: {shortcut}",
            category="system_input",
            action_key="press_shortcut",
        )

    def type_text(self, text: str, *, interval_seconds: float = 0.01, max_chars: int = 1200) -> dict[str, str | bool]:
        self._require_windows_input()
        content = str(text or "")
        if not content:
            raise OSError("Missing text to type.")
        if len(content) > max_chars:
            raise OSError(f"Text is too long for safe typing ({len(content)} chars, max {max_chars}).")

        for char in content:
            if char == "\n":
                self._key_event(self._virtual_key_for("enter"), key_up=False)
                self._key_event(self._virtual_key_for("enter"), key_up=True)
            else:
                self._unicode_key_event(char, key_up=False)
                self._unicode_key_event(char, key_up=True)
            if interval_seconds > 0:
                time.sleep(min(interval_seconds, 0.05))

        return self._result(
            ok=True,
            status="completed",
            message="Napsala jsem text do aktivního okna.",
            detail=f"Typed {len(content)} characters into the active window.",
            category="system_input",
            action_key="type_text",
        )

    def mouse_click(self, x: int, y: int, *, button: str = "left", clicks: int = 1) -> dict[str, str | bool]:
        self._require_windows_input()
        x_pos = int(x)
        y_pos = int(y)
        safe_clicks = max(1, min(int(clicks), 2))
        button_name = str(button or "left").strip().lower()
        button_flags = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }
        if button_name not in button_flags:
            raise OSError(f"Unsupported mouse button: {button}")
        down_flag, up_flag = button_flags[button_name]

        ctypes.windll.user32.SetCursorPos(x_pos, y_pos)
        time.sleep(0.05)
        for _ in range(safe_clicks):
            ctypes.windll.user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.035)
            ctypes.windll.user32.mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.08)

        return self._result(
            ok=True,
            status="completed",
            message=f"Klikla jsem na souřadnice {x_pos}, {y_pos}.",
            detail=f"Mouse clicked {button_name} at {x_pos}, {y_pos}.",
            category="system_input",
            action_key="mouse_click",
        )

    def _optional_open_detail(self, path: Path) -> str:
        try:
            opened_message = self.open_path(path)
            return opened_message
        except OSError as error:
            return f"Created successfully, but opening failed: {error}"

    def _vscode_command(self, vscode_path: str) -> list[str]:
        configured_path = Path(vscode_path.strip().strip('"')).expanduser()
        if configured_path.name.lower() == "code.exe":
            cli_path = configured_path.parent / "bin" / "code.cmd"
            if cli_path.exists():
                return ["cmd", "/c", str(cli_path)]
        if configured_path.suffix.lower() in {".cmd", ".bat"}:
            return ["cmd", "/c", str(configured_path)]
        return [str(configured_path)]

    def open_in_vscode(self, vscode_path: str, target: Path) -> str:
        resolved = Path(target).expanduser().resolve()
        if not vscode_path.strip():
            return self.open_path(resolved)
        subprocess.Popen([*self._vscode_command(vscode_path), "--reuse-window", str(resolved)])
        self._focus_window_by_process_names({"Code.exe"}, timeout_seconds=3.0)
        return f"Opened {resolved} in VS Code"

    def open_web_folder_in_vscode(self, vscode_path: str, web_folder: Path) -> str:
        resolved = Path(web_folder).expanduser().resolve()
        if not resolved.exists():
            raise OSError(f"Web folder does not exist: {resolved}")
        if not resolved.is_dir():
            raise OSError(f"Expected a web folder, got file: {resolved}")

        index_file = resolved / "index.html"
        if not vscode_path.strip():
            return self.open_path(resolved)

        targets = [str(resolved)]
        if index_file.exists():
            targets.append(str(index_file))
        subprocess.Popen([*self._vscode_command(vscode_path), "--reuse-window", *targets])
        self._focus_window_by_process_names({"Code.exe"}, timeout_seconds=3.0)
        if index_file.exists():
            return f"Opened {resolved} and index.html in VS Code"
        return f"Opened {resolved} in VS Code"

    def _npm_run_command(self, script_name: str) -> list[str]:
        if os.name == "nt":
            if script_name == "start":
                return ["cmd", "/c", "npm", "start"]
            return ["cmd", "/c", "npm", "run", script_name]
        if script_name == "start":
            return ["npm", "start"]
        return ["npm", "run", script_name]

    def _detect_npm_run_command(self, workspace: Path) -> tuple[list[str], str] | None:
        package_file = workspace / "package.json"
        if not package_file.exists():
            return None
        try:
            package_data = json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        scripts = package_data.get("scripts", {})
        if not isinstance(scripts, dict):
            return None
        for script_name in ["dev", "start", "build"]:
            if isinstance(scripts.get(script_name), str):
                command = self._npm_run_command(script_name)
                label = "npm start" if script_name == "start" else f"npm run {script_name}"
                return command, label
        return None

    def _detect_python_run_command(self, workspace: Path) -> tuple[list[str], str] | None:
        for relative_entry in ["src/main.py", "main.py", "app.py"]:
            entry = workspace / relative_entry
            if entry.exists() and entry.is_file():
                return [sys.executable, relative_entry], f"python {relative_entry}"
        return None

    def detect_project_run_command(self, workspace: Path) -> tuple[list[str], str] | None:
        target_workspace = Path(workspace).expanduser().resolve()
        return self._detect_npm_run_command(target_workspace) or self._detect_python_run_command(target_workspace)

    def run_static_web_server(self, web_folder: Path, port: int = 8000) -> dict[str, str | bool]:
        target_folder = Path(web_folder).expanduser().resolve()
        if not target_folder.exists() or not target_folder.is_dir():
            return self._result(
                ok=False,
                status="failed",
                message=f"Web slozka neexistuje: {target_folder}",
                detail=f"Expected web folder: {target_folder}",
                category="project_run",
                action_key="run_static_web_server",
                workspace=str(target_folder),
            )
        if not (target_folder / "index.html").exists():
            return self._result(
                ok=False,
                status="failed",
                message=f"Ve slozce {target_folder} chybi index.html.",
                detail="Static web server requires index.html for a useful preview.",
                category="project_run",
                action_key="run_static_web_server",
                workspace=str(target_folder),
            )

        command = [sys.executable, "-m", "http.server", str(port)]
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        if creation_flags:
            subprocess.Popen(command, cwd=str(target_folder), creationflags=creation_flags)
        else:
            subprocess.Popen(command, cwd=str(target_folder))

        url = f"http://localhost:{port}"
        try:
            os.startfile(url)
        except OSError:
            pass

        return self._result(
            ok=True,
            status="in_progress",
            message=f"Spoustim webovy server v {target_folder} na {url}.",
            detail=f"Command: {' '.join(command)}",
            category="project_run",
            action_key="run_static_web_server",
            workspace=str(target_folder),
        )

    def run_project(self, workspace: Path) -> dict[str, str | bool]:
        target_workspace = Path(workspace).expanduser().resolve()
        if not target_workspace.exists():
            return self._result(
                ok=False,
                status="failed",
                message=f"Workspace neexistuje: {target_workspace}",
                detail=f"Project workspace was not found: {target_workspace}",
                category="project_run",
                action_key="run_project",
                workspace=str(target_workspace),
            )

        detected = self.detect_project_run_command(target_workspace)
        if detected is None:
            return self._result(
                ok=False,
                status="failed",
                message="Projekt zatim nema jasny spousteci prikaz.",
                detail="No package.json script or Python entrypoint was found. Expected package.json, src/main.py, main.py, or app.py.",
                category="project_run",
                action_key="run_project",
                workspace=str(target_workspace),
            )

        command, label = detected
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        if creation_flags:
            subprocess.Popen(command, cwd=str(target_workspace), creationflags=creation_flags)
        else:
            subprocess.Popen(command, cwd=str(target_workspace))

        return self._result(
            ok=True,
            status="completed",
            message=f"Spoustim projekt pres `{label}` v {target_workspace}.",
            detail=f"Command: {' '.join(command)}",
            category="project_run",
            action_key="run_project",
            workspace=str(target_workspace),
        )

    def _app_path_for(self, app_key: str, workspace_settings: UserWorkspaceSettings) -> str:
        field_name = self.APP_PATH_FIELDS.get(app_key, "")
        if not field_name:
            return ""
        return str(getattr(workspace_settings, field_name, "") or "").strip()

    def _load_apps_config(self) -> dict[str, str]:
        config_file = Path("config/apps.json")
        try:
            payload = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key).strip().lower(): str(value).strip() for key, value in payload.items() if str(key).strip()}

    def _app_command_candidates(self, app_key: str) -> list[str]:
        aliases = {
            "vscode": ["code", "code.cmd"],
            "chrome": ["chrome", "chrome.exe"],
            "blender": ["blender", "blender.exe"],
            "unreal": ["UnrealEditor", "UnrealEditor.exe", "UE4Editor", "UE4Editor.exe"],
            "unity": ["Unity", "Unity.exe"],
            "discord": ["Discord", "Discord.exe"],
            "explorer": ["explorer", "explorer.exe"],
            "figma": ["Figma", "Figma.exe"],
        }
        return aliases.get(app_key, [app_key, f"{app_key}.exe"])

    def find_app_path(self, app_key: str, workspace_settings: UserWorkspaceSettings | None = None) -> str:
        key = str(app_key or "").strip().lower()
        if not key:
            return ""

        if workspace_settings is not None:
            configured = self._app_path_for(key, workspace_settings)
            if configured:
                configured_path = Path(configured).expanduser()
                if configured_path.exists() or shutil.which(configured):
                    return configured

        apps_config = self._load_apps_config()
        configured = apps_config.get(key, "")
        if configured:
            configured_path = Path(configured).expanduser()
            if configured_path.exists() or shutil.which(configured):
                return configured

        for command_name in self._app_command_candidates(key):
            found = shutil.which(command_name)
            if found:
                return found

        if os.name == "nt":
            for command_name in self._app_command_candidates(key):
                try:
                    completed = subprocess.run(
                        ["where.exe", command_name],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if completed.returncode == 0:
                    first = completed.stdout.splitlines()[0].strip() if completed.stdout.splitlines() else ""
                    if first:
                        return first
        return ""

    def describe_app_path(self, app_key: str, workspace_settings: UserWorkspaceSettings) -> dict[str, str | bool]:
        found = self.find_app_path(app_key, workspace_settings)
        app_name = self.APP_DISPLAY_NAMES.get(app_key, app_key)
        if not found:
            return self._result(
                ok=False,
                status="failed",
                message=f"Nenasla jsem cestu pro {app_name}.",
                detail="Checked user settings, config/apps.json, PATH, and Windows where.exe.",
                category="file_read",
                action_key="find_app_path",
            )
        return self._result(
            ok=True,
            status="completed",
            message=f"Cesta pro {app_name}: {found}",
            detail=f"Resolved app path: {found}",
            category="file_read",
            action_key="find_app_path",
        )

    def _blender_scene_script(self, prompt: str, output_file: Path) -> str:
        prompt_json = json.dumps(str(prompt or "simple LunaAI scene"), ensure_ascii=False)
        output_json = json.dumps(str(output_file), ensure_ascii=False)
        return f'''import math
import os
import bpy

PROMPT = {prompt_json}
OUTPUT_FILE = {output_json}


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def make_material(name, color):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
    material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.42
    material.node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = color[3] * 0.35
    return material


def assign_material(obj, material):
    obj.data.materials.append(material)
    return obj


def add_cube(name, location, scale, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    assign_material(obj, material)
    return obj


def add_cylinder(name, location, radius, depth, material, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    assign_material(obj, material)
    return obj


def add_cone(name, location, radius1, radius2, depth, material, vertices=48):
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius1, radius2=radius2, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    assign_material(obj, material)
    return obj


def add_sphere(name, location, radius, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    assign_material(obj, material)
    return obj


def create_rocket(materials):
    body = add_cylinder("Rocket body", (0, 0, 1.8), 0.55, 3.6, materials["silver"])
    body.rotation_euler[0] = 0
    nose = add_cone("Rocket nose", (0, 0, 3.85), 0.58, 0.02, 1.1, materials["white"])
    flame = add_cone("Engine flame", (0, 0, -0.45), 0.55, 0.08, 1.1, materials["orange"])
    flame.rotation_euler[0] = math.pi
    for index, angle in enumerate((0, 2.094, 4.188)):
        fin = add_cube(f"Stabilizer fin {{index + 1}}", (math.cos(angle) * 0.58, math.sin(angle) * 0.58, 0.25), (0.08, 0.38, 0.55), materials["blue"])
        fin.rotation_euler[2] = angle
    return body


def create_car(materials, offset=(0, 0, 0), name_prefix=""):
    ox, oy, oz = offset
    add_cube(f"{{name_prefix}}AMG C63 body", (ox, oy, oz + 0.45), (2.25, 0.88, 0.24), materials["dark"])
    add_cube(f"{{name_prefix}}AMG C63 hood", (ox + 0.72, oy, oz + 0.62), (0.78, 0.82, 0.12), materials["silver"])
    add_cube(f"{{name_prefix}}AMG C63 cabin", (ox - 0.18, oy, oz + 0.92), (0.8, 0.66, 0.36), materials["white"])
    add_cube(f"{{name_prefix}}AMG C63 rear", (ox - 0.95, oy, oz + 0.62), (0.52, 0.84, 0.16), materials["blue"])
    add_cube(f"{{name_prefix}}front splitter", (ox + 1.2, oy, oz + 0.28), (0.16, 0.9, 0.05), materials["silver"])
    for x in (-1.15, 1.15):
        for y in (-0.62, 0.62):
            wheel = add_cylinder(f"{{name_prefix}}Wheel", (ox + x, oy + y, oz + 0.2), 0.22, 0.18, materials["dark"], vertices=32)
            wheel.rotation_euler[1] = math.pi / 2
    add_cube(f"{{name_prefix}}AMG badge", (ox + 1.24, oy - 0.01, oz + 0.58), (0.03, 0.24, 0.08), materials["orange"])


def create_planet(materials):
    add_sphere("Planet", (0, 0, 1.3), 1.2, materials["blue"])
    ring = add_cylinder("Planet ring", (0, 0, 1.3), 1.85, 0.04, materials["silver"], vertices=96)
    ring.scale.z = 0.05
    ring.rotation_euler[0] = math.radians(82)


def create_room(materials):
    add_cube("Floor", (0, 0, -0.05), (3.4, 3.4, 0.08), materials["dark"])
    add_cube("Back wall", (0, 1.72, 1.4), (3.4, 0.08, 1.5), materials["white"])
    add_cube("Desk", (0, 0.45, 0.45), (1.7, 0.55, 0.12), materials["blue"])
    add_cube("Monitor", (0, 0.72, 1.05), (0.8, 0.05, 0.45), materials["dark"])


def create_abstract(materials):
    add_sphere("Luna core", (0, 0, 1.25), 0.75, materials["silver"])
    for index in range(8):
        angle = index * math.tau / 8
        pillar = add_cube(f"Orbit shard {{index + 1}}", (math.cos(angle) * 1.45, math.sin(angle) * 1.45, 1.1), (0.08, 0.28, 0.65), materials["blue"])
        pillar.rotation_euler[2] = angle


def add_label(text, materials):
    bpy.ops.object.text_add(location=(-1.9, -1.75, 0.1), rotation=(math.radians(75), 0, 0))
    label = bpy.context.object
    label.name = "Scene label"
    label.data.body = text[:72]
    label.data.align_x = "LEFT"
    label.data.size = 0.16
    label.data.extrude = 0.01
    assign_material(label, materials["white"])


def setup_camera_and_light():
    bpy.ops.object.light_add(type="AREA", location=(0, -3.2, 5.0))
    light = bpy.context.object
    light.name = "Softbox"
    light.data.energy = 650
    light.data.size = 4
    bpy.ops.object.camera_add(location=(3.3, -5.2, 3.1), rotation=(math.radians(60), 0, math.radians(34)))
    bpy.context.scene.camera = bpy.context.object


def main():
    lower_prompt = PROMPT.lower()
    add_to_existing = os.path.exists(OUTPUT_FILE) and any(word in lower_prompt for word in (
        "add", "přidej", "pridej", "dej tam", "vedle", "next to", "k tomu", "do toho", "tam"
    ))
    if add_to_existing:
        bpy.ops.wm.open_mainfile(filepath=OUTPUT_FILE)
    else:
        clear_scene()
    materials = {{
        "silver": make_material("lunar silver", (0.72, 0.74, 0.78, 1)),
        "white": make_material("soft white", (0.92, 0.92, 0.88, 1)),
        "blue": make_material("xeno blue", (0.08, 0.22, 0.42, 1)),
        "orange": make_material("warm engine glow", (1.0, 0.32, 0.04, 1)),
        "dark": make_material("matte black", (0.02, 0.02, 0.025, 1)),
    }}
    if any(word in lower_prompt for word in ("rocket", "raket", "ship", "spaceship")):
        create_rocket(materials)
    elif any(word in lower_prompt for word in ("car", "auto", "vehicle", "mercedes", "benz", "amg", "c63")):
        create_car(materials, offset=(2.6, -0.15, 0) if add_to_existing else (0, 0, 0), name_prefix="Added " if add_to_existing else "")
    elif any(word in lower_prompt for word in ("planet", "planeta", "moon", "mesic")):
        create_planet(materials)
    elif any(word in lower_prompt for word in ("room", "mistnost", "workspace", "studio")):
        create_room(materials)
    else:
        create_abstract(materials)
    add_label(("Added: " if add_to_existing else "") + PROMPT, materials)
    if not add_to_existing:
        setup_camera_and_light()
    bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_FILE)


main()
'''

    def create_blender_scene(
        self,
        workspace: Path,
        prompt: str,
        workspace_settings: UserWorkspaceSettings,
    ) -> dict[str, str | bool]:
        target_workspace = Path(workspace).expanduser().resolve()
        if not self._is_inside_workspace_root(target_workspace):
            raise OSError("Blender output must stay inside the LunaAI workspace.")

        scene_folder = target_workspace / "blender"
        scene_folder.mkdir(parents=True, exist_ok=True)
        output_file = scene_folder / "luna_scene.blend"
        script_file = scene_folder / "create_scene.py"
        readme_file = scene_folder / "README.md"
        script_file.write_text(self._blender_scene_script(prompt, output_file), encoding="utf-8")
        readme_file.write_text(
            "# LunaAI Blender Scene\n\n"
            f"Prompt: {prompt.strip() or 'simple LunaAI scene'}\n\n"
            "Run manually with:\n\n"
            "```powershell\n"
            "blender --background --python create_scene.py\n"
            "```\n",
            encoding="utf-8",
        )

        blender_path = self.find_app_path("blender", workspace_settings)
        if not blender_path:
            return self._result(
                ok=True,
                status="needs_setup",
                message=f"Vytvorila jsem Blender script: {script_file}. Nastav cestu k Blenderu a muzu ho rovnou spustit.",
                detail="Blender path was not found in settings, config/apps.json, PATH, or where.exe.",
                category="file_change",
                action_key="create_blender_scene",
                workspace=str(scene_folder),
            )

        completed = subprocess.run(
            [blender_path, "--background", "--python", str(script_file)],
            cwd=str(scene_folder),
            capture_output=True,
            text=False,
            timeout=180,
            check=False,
        )
        output = (self._decode_process_output(completed.stdout) + "\n" + self._decode_process_output(completed.stderr)).strip()
        if len(output) > 4000:
            output = output[:4000].rstrip() + "\n... output zkracen."
        if completed.returncode != 0:
            return self._result(
                ok=False,
                status="failed",
                message="Blender script se nepodarilo spustit.",
                detail=output or f"Blender returned exit code {completed.returncode}.",
                category="file_change",
                action_key="create_blender_scene",
                workspace=str(scene_folder),
            )

        opened_in_blender = False
        focus_confirmed = False
        if output_file.exists():
            try:
                subprocess.Popen([blender_path, str(output_file)])
                opened_in_blender = True
                focus_confirmed = self._focus_window_by_process_names({"blender.exe"}, timeout_seconds=3.0)
            except OSError:
                opened_in_blender = False

        message = "Blender dobehl, ale .blend soubor jsem nenasla."
        if output_file.exists():
            message = f"Blender model je hotovy a otevreny: {output_file}" if opened_in_blender else f"Blender model je hotovy: {output_file}"

        detail_parts = [output or f"Script: {script_file}"]
        if output_file.exists():
            detail_parts.append(f"Blend file: {output_file}")
            detail_parts.append("Opened generated .blend in Blender." if opened_in_blender else "Generated .blend was not opened automatically.")
            if opened_in_blender and not focus_confirmed:
                detail_parts.append("Blender was launched, but foreground focus was not confirmed.")

        return self._result(
            ok=output_file.exists(),
            status="completed" if output_file.exists() else "failed",
            message=message,
            detail="\n".join(detail_parts),
            category="file_change",
            action_key="create_blender_scene",
            workspace=str(scene_folder),
        )

    def _latest_blender_scene_file(self, workspace: Path | None) -> Path | None:
        # If the chat route lost the active project context, still prefer the
        # newest generated .blend instead of opening Blender's empty startup file.
        root = Path(workspace).expanduser() if workspace is not None else self.workspace_root.expanduser()
        if not root.exists() or not root.is_dir():
            return None

        candidates: list[Path] = []
        preferred_folder = root / "blender"
        search_roots = [preferred_folder, root] if preferred_folder.exists() else [root]
        for search_root in search_roots:
            try:
                candidates.extend(
                    path
                    for path in search_root.rglob("*.blend")
                    if path.is_file() and path.suffix.lower() == ".blend"
                )
            except OSError:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    def launch_connected_app(
        self,
        app_key: str,
        workspace_settings: UserWorkspaceSettings,
        project_name: str = "",
    ) -> dict[str, str | bool]:
        app_path = self.find_app_path(app_key, workspace_settings)
        app_name = self.APP_DISPLAY_NAMES.get(app_key, app_key)
        action_key = f"launch_{app_key}"
        if not app_path:
            try:
                result = launch_registered_app(app_key)
                return self._result(ok=bool(result["ok"]), status="completed" if result["ok"] else "failed",
                    message=result["message"], category="app_launch", action_key=action_key)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                return self._result(ok=False, status="failed", message=str(error), category="app_launch", action_key=action_key)

        target_path = Path(app_path)
        if not target_path.exists():
            return self._result(
                ok=False,
                status="failed",
                message=f"Cesta k aplikaci {app_name} nebyla nalezena.",
                detail=f"Configured app path was not found: {app_path}",
                category="app_launch",
                action_key=action_key,
            )

        workspace = self.ensure_project_workspace(project_name) if project_name else None

        try:
            if app_key == "blender":
                blend_file = self._latest_blender_scene_file(workspace)
                if blend_file is not None:
                    if target_path.suffix.lower() in {".exe"}:
                        subprocess.Popen([str(target_path), str(blend_file)])
                    else:
                        os.startfile(str(blend_file))
                    focused = self._focus_window_by_process_names({"blender.exe"}, timeout_seconds=3.0)
                    return self._result(
                        ok=True,
                        status="completed",
                        message=f"Opened Blender project: {blend_file}.",
                        detail=(
                            f"Blender launched with existing .blend file: {blend_file}. "
                            + ("Foreground focus confirmed." if focused else "Foreground focus was not confirmed.")
                        ),
                        category="app_launch",
                        action_key=action_key,
                        workspace=str(workspace or self.workspace_root),
                    )

            if app_key == "vscode":
                if workspace is not None:
                    subprocess.Popen([*self._vscode_command(str(target_path)), "--reuse-window", str(workspace)])
                    return self._result(
                        ok=True,
                        status="completed",
                        message=f"Opened {workspace} in VS Code.",
                        detail=f"VS Code launched with workspace {workspace}",
                        category="app_launch",
                        action_key=action_key,
                        workspace=str(workspace),
                    )
                subprocess.Popen(self._vscode_command(str(target_path)), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return self._result(
                    ok=True,
                    status="completed",
                    message="Opened VS Code.",
                    detail="VS Code launched.",
                    category="app_launch",
                    action_key=action_key,
                )

            if target_path.is_dir():
                self.open_path(target_path)
                return self._result(
                    ok=True,
                    status="completed",
                    message=f"Opened {app_name}.",
                    detail=f"Opened directory target for {app_name}.",
                    category="app_launch",
                    action_key=action_key,
                )

            if target_path.suffix.lower() in {".lnk", ".url", ".exe"}:
                os.startfile(str(target_path))
            else:
                subprocess.Popen([str(target_path)])
        except OSError as error:
            return self._result(
                ok=False,
                status="failed",
                message=f"{app_name} se nepodarilo otevrit.",
                detail=f"Could not launch the app: {error}",
                category="app_launch",
                action_key=action_key,
                workspace=str(workspace or ""),
            )

        if workspace is not None:
            return self._result(
                ok=True,
                status="completed",
                message=f"Opened {app_name}. Project workspace is ready at {workspace}.",
                detail=f"{app_name} launched and workspace is ready.",
                category="app_launch",
                action_key=action_key,
                workspace=str(workspace),
            )
        return self._result(
            ok=True,
            status="completed",
            message=f"Opened {app_name}.",
            detail=f"{app_name} launched.",
            category="app_launch",
            action_key=action_key,
        )

    def _is_inside_workspace_root(self, path: Path) -> bool:
        resolved = Path(path).expanduser().resolve()
        allowed_roots = [Path.cwd().resolve(), self.workspace_root.expanduser().resolve()]
        for root in allowed_roots:
            if resolved == root or root in resolved.parents:
                return True
        return False

    def _safe_command_parts(self, command_text: str) -> tuple[list[str], str, bool]:
        cleaned = str(command_text or "").strip()
        if not cleaned:
            raise OSError("Missing command.")
        if re.search(r"[|&;><`]", cleaned):
            raise OSError("Shell chaining, redirection, and pipes are blocked.")
        if re.search(
            r"\b(del|erase|rm|rmdir|rd|format|shutdown|restart-computer|stop-computer|regedit|reg|diskpart|bcdedit|takeown|icacls|taskkill|system32|runas|sudo)\b",
            cleaned,
            flags=re.IGNORECASE,
        ):
            raise OSError("This command is blocked by safety policy.")

        lowered = cleaned.lower()
        if lowered == "dir":
            return [], "dir", False
        if lowered.startswith("echo "):
            return [], cleaned, False

        try:
            parts = shlex.split(cleaned, posix=False)
        except ValueError as error:
            raise OSError(f"Could not parse command safely: {error}") from error
        if not parts:
            raise OSError("Missing command.")

        executable = parts[0].lower()
        if executable in {"npm", "npm.cmd"}:
            if len(parts) == 2 and parts[1].lower() == "start":
                return self._npm_run_command("start"), "npm start", True
            if len(parts) >= 2 and parts[1].lower() in {"install", "i", "add"}:
                if len(parts) > 8:
                    raise OSError("Too many packages requested in one install command.")
                if any(not re.fullmatch(r"[@a-zA-Z0-9._/\-]+", part) for part in parts[2:]):
                    raise OSError("Package name contains unsupported characters.")
                if os.name == "nt":
                    return ["cmd", "/c", *parts], " ".join(parts), True
                return parts, " ".join(parts), True
            if len(parts) == 3 and parts[1].lower() == "run" and parts[2].lower() in {"dev", "start", "build", "test"}:
                return self._npm_run_command(parts[2].lower()), f"npm run {parts[2].lower()}", parts[2].lower() in {"dev", "start"}
            raise OSError("Only npm start and npm run dev/start/build/test are allowed.")

        if executable in {"python", "python.exe", "py", "py.exe"}:
            if len(parts) == 2 and parts[1].replace("\\", "/").lower() in {"main.py", "src/main.py", "app.py"}:
                return [sys.executable, parts[1]], f"python {parts[1]}", False
            if len(parts) == 3 and parts[1] == "-m" and parts[2].lower() in {"pytest"}:
                return [sys.executable, "-m", parts[2]], f"python -m {parts[2]}", False
            raise OSError("Only python main.py, python src/main.py, python app.py, and python -m pytest are allowed.")

        if executable == "pytest":
            return ["pytest"], "pytest", False

        raise OSError(f"Command '{parts[0]}' is not in the safe allowlist.")

    def run_safe_command(self, command_text: str, workspace: Path | None = None, timeout_seconds: int = 25) -> dict[str, str | bool]:
        target_workspace = Path(workspace or Path.cwd()).expanduser().resolve()
        if not target_workspace.exists() or not target_workspace.is_dir():
            raise OSError(f"Working directory does not exist: {target_workspace}")
        if not self._is_inside_workspace_root(target_workspace):
            raise OSError("Command working directory must stay inside the LunaAI workspace.")

        command, label, long_running = self._safe_command_parts(command_text)
        lowered = str(command_text or "").strip().lower()
        if lowered == "dir":
            return self._result(
                ok=True,
                status="completed",
                message=self.list_folder(target_workspace),
                detail=f"Listed {target_workspace}",
                category="project_run",
                action_key="run_command",
                workspace=str(target_workspace),
            )
        if lowered.startswith("echo "):
            message = str(command_text).strip()[5:].strip()
            return self._result(
                ok=True,
                status="completed",
                message=message,
                detail=f"Echo command returned: {message}",
                category="project_run",
                action_key="run_command",
                workspace=str(target_workspace),
            )

        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        if long_running:
            if creation_flags:
                subprocess.Popen(command, cwd=str(target_workspace), creationflags=creation_flags)
            else:
                subprocess.Popen(command, cwd=str(target_workspace))
            return self._result(
                ok=True,
                status="in_progress",
                message=f"Spoustim `{label}` v {target_workspace}.",
                detail=f"Started long-running command: {' '.join(command)}",
                category="project_run",
                action_key="run_command",
                workspace=str(target_workspace),
            )

        completed = subprocess.run(
            command,
            cwd=str(target_workspace),
            capture_output=True,
            text=True,
            timeout=max(3, timeout_seconds),
            check=False,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        output = stdout or stderr or f"Exit code {completed.returncode}"
        if len(output) > 4000:
            output = output[:4000].rstrip() + "\n... output zkracen."
        return self._result(
            ok=completed.returncode == 0,
            status="completed" if completed.returncode == 0 else "failed",
            message=f"`{label}` dokonceno." if completed.returncode == 0 else f"`{label}` skoncilo chybou.",
            detail=output,
            category="project_run",
            action_key="run_command",
            workspace=str(target_workspace),
        )

    def get_system_info(self) -> dict[str, str | bool]:
        detail = "\n".join(
            [
                f"OS: {platform.system()} {platform.release()}",
                f"Version: {platform.version()}",
                f"Machine: {platform.machine()}",
                f"Python: {platform.python_version()}",
                f"User: {os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}",
                f"Workspace: {Path.cwd()}",
            ]
        )
        return self._result(
            ok=True,
            status="completed",
            message="System info retrieved.",
            detail=detail,
            category="file_read",
            action_key="get_system_info",
        )

    def run_task_action(
        self,
        *,
        project_name: str,
        brief: str,
        next_step: str,
        task: dict[str, object],
        workspace_settings: UserWorkspaceSettings,
    ) -> dict[str, str | bool]:
        task_title = str(task.get("title", "Task"))
        normalized = task_title.strip().lower()
        action_hint = str(task.get("action_hint", "")).strip().lower()
        handoff_note = str(task.get("handoff_note", "")).strip()
        workspace = self.ensure_project_workspace(project_name)
        action_meta = self.describe_action_hint(action_hint)
        category = action_meta.get("category", "system")

        if action_hint == "create_scope_file" or any(token in normalized for token in ["scope", "clarify the real target", "lock the first milestone"]):
            created = self.create_scope_file(project_name, brief)
            open_detail = self._optional_open_detail(created)
            message = handoff_note or f"Task agent prepared the project scope at {created}."
            return self._result(ok=True, status="completed", message=message, detail=f"Scope file prepared: {created}. {open_detail}", category=category, action_key=action_hint or "create_scope_file", workspace=str(workspace))

        if action_hint == "create_execution_plan" or any(token in normalized for token in ["execution path", "map the execution path", "implementation stack"]):
            created = self.create_execution_plan_file(project_name, next_step)
            open_detail = self._optional_open_detail(created)
            message = handoff_note or f"Task agent created the execution plan at {created}."
            return self._result(ok=True, status="completed", message=message, detail=f"Execution plan updated: {created}. {open_detail}", category=category, action_key=action_hint or "create_execution_plan", workspace=str(workspace))

        if action_hint == "create_project_scaffold" or any(token in normalized for token in ["workspace", "implementation structure", "scaffold", "prepare local workspace"]):
            created_workspace = self.create_project_scaffold(project_name, brief)
            message = handoff_note or f"Task agent created the project workspace structure in {created_workspace}."
            return self._result(ok=True, status="completed", message=message, detail=f"Workspace scaffold ready: {created_workspace}", category=category, action_key=action_hint or "create_project_scaffold", workspace=str(created_workspace))

        if action_hint == "open_workspace_in_tool" or any(token in normalized for token in ["working slice", "milestone", "build the first working slice"]):
            created_workspace = self.create_project_scaffold(project_name, brief)
            vscode_message = self.open_in_vscode(workspace_settings.vscode_path, created_workspace)
            message = handoff_note or f"Task agent prepared the workspace and {vscode_message.lower()}."
            return self._result(ok=True, status="in_progress", message=message, detail=f"Workspace opened for implementation: {created_workspace}", category=category, action_key=action_hint or "open_workspace_in_tool", workspace=str(created_workspace))

        if action_hint == "refresh_review_notes" or any(token in normalized for token in ["review quality", "review and harden", "next step"]):
            created = self.create_execution_plan_file(project_name, next_step)
            message = handoff_note or f"Task agent refreshed the review notes and next-step file at {created}."
            return self._result(ok=True, status="completed", message=message, detail=f"Review notes refreshed: {created}", category=category, action_key=action_hint or "refresh_review_notes", workspace=str(workspace))

        open_detail = self._optional_open_detail(workspace)
        return self._result(ok=True, status="in_progress", message=handoff_note or f"Task agent prepared the project workspace at {workspace} for the next manual step.", detail=f"Workspace ready: {workspace}. {open_detail}", category="path_open", action_key=action_hint or "open_workspace", workspace=str(workspace))
