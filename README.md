# PGEX-AI-01

Local AI system that can run, inspect, and help debug projects directly on your PC.

## What It Does

- Runs local projects
- Detects and explains errors
- Suggests practical fixes
- Opens and controls desktop apps such as VS Code

## System Layers

- `Luna`: user-facing communication and guidance
- `Xeno`: planning, reasoning, and project shaping
- `Agent`: local execution and action routing
- `Vision`: screen observation and visual analysis

## Stack

- Python backend
- Electron shell
- React frontend
- OpenAI / NVIDIA model integrations
- Local desktop tooling

## Status

Work in progress.

## Praktické využití

Asistentka se jmenuje Luna, aplikace a projekt PGEX-AI-01.

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
