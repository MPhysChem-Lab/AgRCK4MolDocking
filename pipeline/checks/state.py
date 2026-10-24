"""Gate state helpers shared by agrck and the pipeline scripts (so running a script directly still reopens gates)."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

ORDER = ["E0", "E1", "E2", "E3", "E4", "E5", "E6"]


def study_root(path: str | Path) -> Path | None:
    """The study directory (contains estudo.yaml) at or above path, if any."""
    p = Path(path).resolve()
    for d in [p, *p.parents]:
        if (d / "estudo.yaml").exists() and d.parent.name == "estudos":
            return d
    return None


def sync_progress(d: Path, st: dict, line: str | None = None) -> None:
    """Mirror gate state in progress.md checkboxes and append a history line."""
    p = d / "progress.md"
    if not p.exists():
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"- \[[ x]\] (E\d) ", ln)
        if m:
            lines[i] = ("- [x] " if st.get(m.group(1), {}).get("ok") else "- [ ] ") + ln[6:]
    if line:
        lines.append(f"- {dt.datetime.now():%Y-%m-%d %H:%M} — {line}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def reopen(path: str | Path, gate: str) -> list[str]:
    """Drop `gate` and every later gate from the study's .portoes.json; returns what was dropped."""
    d = study_root(path)
    if d is None or not (d / ".portoes.json").exists():
        return []
    st = json.loads((d / ".portoes.json").read_text())
    drop = [g for g in ORDER[ORDER.index(gate):] if g in st]
    for g in drop:
        st.pop(g)
    (d / ".portoes.json").write_text(json.dumps(st, indent=1))
    if drop:
        sync_progress(d, st, f"script do pipeline rodou: portões {drop} reabertos")
    return drop
