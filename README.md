# PGEX-AI-01

PGEX-AI-01 is a local AI system designed to run on your PC and help you build, debug and control projects directly from your desktop.

This project is part of Program Envus Xenos — a long-term vision focused on intelligent systems, operating systems, automation and advanced technology.

## 🚀 What it does

- Runs and manages projects on your PC
- Detects errors and explains what went wrong
- Suggests fixes and improvements
- Opens and controls apps like VS Code
- Helps with coding, workflow and development
- Works as an assistant, not as a replacement

## 🧠 System

- **Luna** — communication, explanation and user interaction
- **Xeno** — logic, reasoning and problem solving
- **Agent** — executes actions on your PC
- **Vision** — reads the screen and detects issues

## 🎯 Goal

To create an AI that works *with you*, not instead of you.

PGEX-AI-01 is built to become a personal intelligent system that connects software, tools and local PC control into one workflow.

## 🛠 Tech

- Electron
- Node.js
- Python
- OpenAI / NVIDIA models
- Local system integration

## 📌 Status

Work in progress.

## 🔮 Future

- Mobile control
- Memory system
- Voice control
- Better Vision system
- Integration with VS Code, Blender, Unreal Engine and more tools
- Deeper local PC automation
- Future connection with EthernOS / PGEX ecosystem

## Praktické využití

Aplikace se jmenuje PGEX, asistentka Luna a repozitář projektu PGEX-AI-01.

- **Texty a plánování:** „Rozděl tento úkol na kroky“ nebo „Uprav tento návrh e-mailu“.
- **Čitelné soubory a kód:** přilož TXT, Markdown, Python nebo JavaScript a požádej o shrnutí či vysvětlení chyby.
- **Obrázky a screenshoty:** přilož obrázek nebo snímek obrazovky a požádej o vysvětlení viditelné chyby.
- **Projekty:** organizuj konverzace podle témat.
- **Desktopové aplikace:** nastav cestu k VS Code či jiné podporované aplikaci a použij lokální akce asistenta.

PDF a kancelářské dokumenty vyžadují další parser; automatizaci desktopu ověřuj na konkrétní úloze. Samotný pozdrav neověřuje všechny schopnosti.

Inspirace a technické zdroje:
- https://docs.nvidia.com/nemotron/latest/use-case-examples/README.html
- https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning

## Otevření a ověření

Otevři `PGEX-AI-01.code-workspace` ve VS Code. Zdrojové soubory zůstávají v původním adresáři, aby se nerozbily lokální cesty a Python prostředí.

```powershell
npm run dev
npm run build
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
