"""Pre-delivery check of a LaTeX/Markdown report: compile log, leftover template branding, agent/code
jargon in the text, missing figures, over-claiming (claim_lint).

python report_check.py REPORT_DIR [--main main.tex] [--forbid "TU/e,Eindhoven"]
Exit 1 on any blocking finding. Inspecting every PDF page visually is still required afterwards.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from . import claim_lint
except ImportError:  # run as a script
    import claim_lint  # type: ignore

FORBIDDEN = ["PREENCHER", "TU/e", "Eindhoven", "Technische Universiteit", "Lorem ipsum", "MiniDock", "AgRCK", "Antigravity",
             "Claude", "Codex", "No License File", "For Evaluation Only"]
CODE_JARGON = re.compile(r"\b\w+\.py\b|\b(site_distance_A|pb_pass|pb_failed|min_shift_A|n_poses_\w+|cnn_score|"
                         r"cnn_affinity|le_vina|diffdock_confidence|rmsd_to_reference)\b")
OVERFULL = re.compile(r"Overfull \\hbox \((\d+(?:\.\d+)?)pt too wide\)")


def _strip_tex_comments(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", ln) for ln in text.splitlines())


def _included(report_dir: Path, main: str) -> list[Path]:
    """main.tex plus every file reached through \\input/\\include (unused template files are ignored)."""
    seen, todo = [], [report_dir / main]
    while todo:
        p = todo.pop()
        if p in seen or not p.exists():
            continue
        seen.append(p)
        body = _strip_tex_comments(p.read_text(encoding="utf-8", errors="replace"))
        for m in re.finditer(r"\\(?:input|include)\{([^}]+)\}", body):
            q = report_dir / m.group(1)
            todo.append(q if q.suffix == ".tex" else q.with_name(q.name + ".tex"))
    return seen


def check(report_dir: Path, main: str, extra_forbidden: list[str], max_overfull_pt: float) -> list[str]:
    errs: list[str] = []
    texts = _included(report_dir, main) if (report_dir / main).exists() else sorted(report_dir.rglob("*.md"))
    for p in texts:
        raw = p.read_text(encoding="utf-8", errors="replace")
        body = _strip_tex_comments(raw) if p.suffix == ".tex" else raw
        for word in FORBIDDEN + extra_forbidden:
            if word and word in body:
                errs.append(f"{p.name}: texto proibido '{word}' (resto de template ou jargão do agente)")
        for n, line in enumerate(body.splitlines(), 1):
            if "lint-ok" in line or "\\includegraphics" in line or "\\input" in line or "\\label" in line \
                    or "\\ref" in line or "\\cite" in line:
                continue
            m = CODE_JARGON.search(line)
            if m:
                errs.append(f"{p.name}:{n}: jargão de código '{m.group(0)}' no texto (use notação físico-química)")
        for n, word, sug in claim_lint.lint_text(raw):
            errs.append(f"{p.name}:{n}: afirmação forte '{word}' -> {sug}")
        for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", body):
            f = m.group(1)
            cands = [report_dir / f] + [report_dir / (f + ext) for ext in (".png", ".pdf", ".jpg")]
            if not any(c.exists() for c in cands):
                errs.append(f"{p.name}: figura ausente '{f}'")
    log = report_dir / Path(main).with_suffix(".log").name
    if (report_dir / main).exists():
        if not log.exists():
            errs.append(f"{log.name} não encontrado: compile o relatório antes da checagem")
        else:
            lt = log.read_text(encoding="latin-1", errors="replace")
            if re.search(r"^! ", lt, re.M):
                errs.append("erros de compilação LaTeX ('! ' no log)")
            if "undefined references" in lt or re.search(r"Reference `[^']+' on page \d+ undefined", lt):
                errs.append("referências cruzadas indefinidas (rode pdflatex de novo / confira \\label)")
            if "Citation" in lt and "undefined" in lt:
                errs.append("citações indefinidas (rode bibtex)")
            big = [float(x) for x in OVERFULL.findall(lt) if float(x) > max_overfull_pt]
            if big:
                errs.append(f"{len(big)} overfull hbox > {max_overfull_pt:g} pt (máx {max(big):.1f} pt): texto/tabela estourando a margem")
    return errs


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report_dir")
    ap.add_argument("--main", default="main.tex")
    ap.add_argument("--forbid", default="", help="strings extras proibidas, separadas por vírgula")
    ap.add_argument("--max-overfull-pt", type=float, default=5.0)
    a = ap.parse_args(argv)
    errs = check(Path(a.report_dir), a.main, [s.strip() for s in a.forbid.split(",") if s.strip()], a.max_overfull_pt)
    for e in errs:
        print("✗", e)
    print("report_check:", "OK (agora inspecione cada página do PDF)" if not errs else f"{len(errs)} problema(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
