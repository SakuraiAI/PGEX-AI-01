"""Windows registered applications, shared by chat and Electron. No shell commands from user input."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

ALIASES = {
    "vscode": ["vs code", "visual studio code", "vscodu", "vs codu"],
    "chrome": ["google chrome", "chrom"],
    "unreal": ["unreal engine", "unreal engine 5", "ue5"],
    "notepad": ["poznamkovy blok", "poznamky"],
    "calculator": ["kalkulacka", "kalkulator"],
    "fl_studio": ["fl studio"], "davinci": ["davinci resolve"],
    "premiere": ["adobe premiere pro", "premiere pro"],
    "after_effects": ["adobe after effects", "after effects"],
    "substance": ["substance 3d painter", "substance painter"],
}
_cache: tuple[float, list[dict]] = (0, [])

def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def parse_applications(rows) -> list[dict]:
    if isinstance(rows, dict): rows = [rows]
    result = {}
    for row in rows or []:
        name, app_id = str(row.get("Name", "")).strip(), str(row.get("AppID", "")).strip()
        if not name or not app_id: continue
        # Exclude documentation and removal shortcuts from the app picker.
        if re.search(r"\.(txt|pdf|html?|url)$", app_id, re.I) or re.search(r"\b(uninstall|odinstalovat)\b", name, re.I): continue
        if "://" in app_id and not app_id.startswith("steam://rungameid/"): continue
        if any(c in app_id for c in "\r\n\0"): continue
        key = 'windows-' + hashlib.sha256(app_id.encode()).hexdigest()[:20]
        result[key] = {"id": key, "key": key, "title": name, "appId": app_id,
                       "target": app_id if app_id.startswith("steam://rungameid/") else "shell:AppsFolder\\" + app_id,
                       "connected": True, "status": "Nalezeno ve Windows", "detail": "Spuštění podle názvu"}
    return sorted(result.values(), key=lambda item: normalize(item["title"]))

def list_applications(*, refresh=False) -> list[dict]:
    global _cache
    if not refresh and _cache[0] and time.monotonic() - _cache[0] < 60: return _cache[1]
    if os.name != "nt": return []
    script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); $ErrorActionPreference = 'Stop'; @(Get-StartApps | Select-Object Name,AppID) | ConvertTo-Json -Compress"
    try:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8-sig", timeout=15, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.SubprocessError as error:
        raise OSError("Windows nevrátil seznam aplikací včas.") from error
    apps = parse_applications(json.loads(completed.stdout or "[]"))
    _cache = (time.monotonic(), apps)
    return apps

def find_registered_app(query: str, apps=None) -> dict | None:
    apps = list_applications() if apps is None else apps
    raw = str(query or '').strip()
    exact_id = [item for item in apps if item['key'] == raw or item['appId'].lower() == raw.lower()]
    if exact_id: return exact_id[0]
    name = normalize(raw)
    if not name: return None
    names = {name}
    for canonical, aliases in ALIASES.items():
        group = {normalize(canonical), *(normalize(alias) for alias in aliases)}
        if name in group: names.update(group)
    exact = [item for item in apps if normalize(item['title']) in names]
    matches = exact or [item for item in apps if any(normalize(item['title']).startswith(n + ' ') for n in names)]
    if len(matches) > 1:
        raise ValueError('Název je nejednoznačný. Vyber: ' + ', '.join(item['title'] for item in matches))
    return matches[0] if matches else None

def launch_registered_app(query: str) -> dict:
    item = find_registered_app(query)
    if not item: return {"ok": False, "message": "Aplikace nebyla nalezena ve Windows. Zkontroluj, zda je nainstalovaná."}
    os.startfile(item['target'])
    return {"ok": True, "message": f"Spuštění aplikace {item['title']} předáno Windows.", "app": item}

if __name__ == '__main__':
    try:
        command = sys.argv[1] if len(sys.argv) > 1 else 'list'
        query = sys.argv[2] if len(sys.argv) > 2 else ''
        if command == 'list': result = {"ok": True, "apps": list_applications(refresh=True)}
        elif command == 'resolve': result = {"ok": True, "app": find_registered_app(query)}
        elif command == 'launch': result = launch_registered_app(query)
        else: result = {"ok": False, "message": "Neznámá operace."}
    except Exception as error:
        result = {"ok": False, "message": f"Aplikace Windows se nepodařilo zpracovat: {error}"}
    print(json.dumps(result, ensure_ascii=True))
