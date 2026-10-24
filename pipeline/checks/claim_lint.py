"""Flag over-claiming language in reports (.md/.tex). Docking generates hypotheses; it does not prove.

python claim_lint.py FILE [FILE ...]      exit 1 if any finding
A line containing 'lint-ok' is skipped (use only with a justification on the same line).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# (pattern, suggestion). Case-insensitive; written for PT-BR and EN.
_NOT_EXP = r"(?!\s+(experimental|em ensaio|por ensaio|in vitro))"   # "a confirmar experimentalmente" is fine
RULES = [
    (r"\bcomprova(m|r|do|da|ndo|ção)?\b" + _NOT_EXP, "use 'sugere' / 'é compatível com'"),
    (r"\bprova(m|r)? que\b", "use 'sugere que'"),
    (r"\bdemonstra(m|r)? que\b", "use 'indica que' / 'sugere que'"),
    (r"(?<!a )\bconfirma(m|r|do|da|ndo)?\b" + _NOT_EXP,
     "docking não confirma; use 'é consistente com' (confirmação = experimento)"),
    (r"\belucida(m|r|do|da)?\b", "use 'propõe uma explicação estrutural'"),
    (r"\bgarant(e|em|ir|ido)\b", "use 'favorece' / 'é compatível com'"),
    (r"\binequ[ií]voc", "evite certeza absoluta em modelagem"),
    (r"\bdefinitivamente\b|\bindiscutivelmente\b", "evite certeza absoluta"),
    (r"\bvalidad[oa]s? como\b", "um ligante não é 'validado como' modo de ligação; diga 'a pose sugere'"),
    (r"\bindispens[aá]ve(l|is)\b", "use 'requisito importante segundo o modelo'"),
    (r"\bracionaliza[çc][ãa]o completa\b", "use 'hipótese estrutural'"),
    (r"\b(proves?|proven|demonstrates? that|confirms?|confirmed|elucidates?|unequivocal(ly)?)\b",
     "docking suggests; it does not prove/confirm"),
    (r"energia livre (de liga[çc][ãa]o )?(experimental|real)", "Vina/CNN não são ΔG experimental"),
    (r"\b(IC50|Ki|Kd)\s*(previsto|predito|calculado)", "escores de docking não são IC50/Ki/Kd"),
    (r"\bpot[eê]ncia (prevista|calculada)\b", "use 'escore'; potência é medida experimental"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), s) for p, s in RULES]


def lint_text(text: str) -> list[tuple[int, str, str]]:
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        if "lint-ok" in line or line.lstrip().startswith("%"):
            continue
        for rx, sug in _COMPILED:
            m = rx.search(line)
            if m:
                found.append((n, m.group(0), sug))
    return found


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = (argv if argv is not None else sys.argv[1:])
    total = 0
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        for n, word, sug in lint_text(p.read_text(encoding="utf-8", errors="replace")):
            print(f"{p}:{n}: '{word}' -> {sug}")
            total += 1
    if total:
        print(f"claim_lint: {total} afirmacao(oes) forte(s) demais. Reescreva como hipotese.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
