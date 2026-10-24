"""PostToolUse: after an edit to a report (.tex/.md under relatorio/ or RESUMO.md) run claim_lint; after an edit
to memoria/MEMORIA.md require a source on every dated fact. Findings go back to the agent (exit 2 + stderr).
Claude payload: tool_input.file_path. Codex apply_patch: every '*** Add/Update File:' path in the patch text.
Stdlib only; silent for every other file."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline" / "checks"))
FACT = re.compile(r"^\s*-\s*\d{4}-\d{2}-\d{2}")


def edited_paths(data: dict) -> list[Path]:
    ti = data.get("tool_input", {}) or {}
    if isinstance(ti, str):
        ti = {"input": ti}
    paths = [ti.get("file_path") or ti.get("path") or ""]
    for v in ti.values():
        if isinstance(v, str):
            paths += re.findall(r"^\*\*\* (?:Add|Update) File: (.+?)\s*$", v, re.M)
    cwd = Path(data.get("cwd") or ".")
    return [p if p.is_absolute() else cwd / p for p in (Path(x) for x in paths if x)]


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    msgs = []
    for p in edited_paths(data):
        if not p.is_file():
            continue
        if p.name == "MEMORIA.md":
            bad = [n for n, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                   if FACT.match(l) and "fonte:" not in l.lower()]
            msgs += [f"{p.name}:{n}: fato sem '(fonte: arquivo/CSV)'; interpretação vai no relatório" for n in bad]
        elif p.suffix in (".tex", ".md") and ("relatorio" in p.parts or p.name == "RESUMO.md"):
            import claim_lint
            msgs += [f"{p.name}:{n}: '{w}' -> {s}"
                     for n, w, s in claim_lint.lint_text(p.read_text(encoding="utf-8", errors="replace"))]
    if msgs:
        sys.stderr.write("AgRCK — corrija antes de seguir (docking sugere, não comprova; memória só com fonte):\n"
                         + "\n".join(msgs[:15]) + "\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
