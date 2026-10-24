#!/bin/sh
# Codex setup: agrck on PATH, AGENTS.md in the current workspace, guard/lint hooks in ~/.codex/hooks.json.
# Asks before touching ~/.codex. Re-running is safe (idempotent).
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.local/bin"
ln -sf "$REPO/bin/agrck" "$HOME/.local/bin/agrck"
echo "agrck -> $HOME/.local/bin/agrck"
[ -f AGENTS.md ] || { cp "$REPO/AGENTS.md" AGENTS.md; echo "AGENTS.md copiado para $(pwd)"; }

HOOKS="$HOME/.codex/hooks.json"
printf "Adicionar hooks do AgRCK em %s? [s/N] " "$HOOKS"
read -r ans
case "$ans" in s|S|y|Y) ;; *) echo "hooks não instalados"; exit 0 ;; esac
mkdir -p "$HOME/.codex"
PY=$(command -v python3 || command -v python)
"$PY" - "$HOOKS" "$REPO" <<'EOF'
import json, sys
from pathlib import Path
path, repo = Path(sys.argv[1]), sys.argv[2]
data = json.loads(path.read_text()) if path.exists() else {}
hooks = data.setdefault("hooks", {})
def add(event, matcher, script):
    cmd = f'sh "{repo}/hooks/run.sh" {script}'
    groups = hooks.setdefault(event, [])
    if not any(h.get("command") == cmd for g in groups for h in g.get("hooks", [])):
        groups.append({"matcher": matcher, "hooks": [{"type": "command", "command": cmd, "timeout": 20}]})
add("PreToolUse", ".*", "guard.py")
add("PostToolUse", ".*", "lint_report.py")
path.write_text(json.dumps(data, indent=2))
print(f"hooks gravados em {path}. No Codex, aprove-os com /hooks.")
EOF
