"""PostToolUse: after an edit to a report (.tex/.md under relatorio/ or RESUMO.md), run claim_lint and feed
the findings back to the agent (exit 2 + stderr). Stdlib only; silent for every other file."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline" / "checks"))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    ti = data.get("tool_input", {}) or {}
    path = str(ti.get("file_path") or ti.get("path") or "")
    if not path:  # Codex apply_patch: take the first patched file
        m = re.search(r"\*\*\* (?:Add|Update) File: (\S+)", json.dumps(ti))
        path = m.group(1) if m else ""
    p = Path(path)
    if p.suffix not in (".tex", ".md") or not ("relatorio" in p.parts or p.name == "RESUMO.md") or not p.is_file():
        return
    import claim_lint
    found = claim_lint.lint_text(p.read_text(encoding="utf-8", errors="replace"))
    if found:
        lines = [f"{p.name}:{n}: '{w}' -> {s}" for n, w, s in found[:12]]
        sys.stderr.write("AgRCK claim_lint — reescreva como hipótese (docking sugere, não comprova):\n"
                         + "\n".join(lines) + "\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
