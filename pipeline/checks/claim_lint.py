"""Flag over-claiming language in reports (.md/.tex). Docking generates hypotheses; it does not prove.

python claim_lint.py FILE [FILE ...]      exit 1 if any finding (or a file is missing)
Escape hatch: 'lint-ok: <reason>' on the same line (reason required, e.g. a literal quotation).
Negated forms ('não comprova', 'does not prove') are the recommended wording and are never flagged.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

W = r"(?![\wçãõáéíóúâêôà])"            # word end that also respects Portuguese accented letters
_EXP = r"(?!\s+(experimental|em ensaio|por ensaio|in vitro|experimentally))"
# (pattern, suggestion). Case-insensitive; PT-BR and EN.
RULES = [
    (r"\bcomprov(a|am|ar|ou|aram|ado|ada|ados|adas|ando|ação|ações)" + W + _EXP, "use 'sugere' / 'é compatível com'"),
    (r"\bprova(m|r|ram|u)? que\b", "use 'sugere que'"),
    (r"\bdemonstr(a|am|ou|aram)" + W + r" que\b", "use 'indica que' / 'sugere que'"),
    (r"\bconfirm(a|am|ou|aram|ado|ada|ados|adas|ando|ação|ações)" + W + _EXP + r"|(?<!\ba )\bconfirmar" + W + _EXP,
     "docking não confirma; use 'é consistente com' (confirmação = experimento)"),
    (r"\belucid(a|am|ar|ou|ado|ada|ação)" + W, "use 'propõe uma explicação estrutural'"),
    (r"\brevela(m|ram|u)? que\b", "use 'sugere que'"),
    (r"\bgarant(e|em|ir|ido|iu)" + W, "use 'favorece' / 'é compatível com'"),
    (r"\binequ[ií]voc", "evite certeza absoluta em modelagem"),
    (r"\bdefinitivamente\b|\bindiscutivelmente\b|\bsem dúvida\b", "evite certeza absoluta"),
    (r"\bvalidad[oa]s? como\b", "um ligante não é 'validado como' modo de ligação; diga 'a pose sugere'"),
    (r"\bindispens[aá]ve(l|is)" + W, "use 'requisito importante segundo o modelo'"),
    (r"\bracionaliza[çc][ãa]o completa\b", "use 'hipótese estrutural'"),
    (r"\b(proves?|proven|proved|demonstrates? that|demonstrated that|confirms?|confirmed|elucidates?|elucidated|"
     r"unequivocal(ly)?|reveals? that|established that|validated as)\b" + _EXP,
     "docking suggests; it does not prove/confirm"),
    (r"energia livre (de liga[çc][ãa]o )?(experimental|real)", "Vina/CNN não são ΔG experimental"),
    (r"\b(IC50|Ki|Kd)\s*(previsto|predito|calculado|predicted|calculated)", "escores de docking não são IC50/Ki/Kd"),
    (r"\bpot[eê]ncia (prevista|calculada)\b", "use 'escore'; potência é medida experimental"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), s) for p, s in RULES]
NEGATION = re.compile(r"\b(não|nao|nunca|nem|sem|not|cannot|can't|does not|do not|did not|never|no)\s+"
                      r"((?!só\b|apenas\b|somente\b|only\b|just\b|merely\b)\w+\s+)?$", re.IGNORECASE)
LINT_OK = re.compile(r"lint-ok:\s*\S+\s+\S+\s+\S+", re.IGNORECASE)   # reason of at least 3 words


def lint_text(text: str) -> list[tuple[int, str, str]]:
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        if LINT_OK.search(line) or line.lstrip().startswith("%"):
            continue
        for rx, sug in _COMPILED:
            for m in rx.finditer(line):
                before = line[max(0, m.start() - 25):m.start()]
                if NEGATION.search(before) and not re.search(r"sem dúvida", m.group(0), re.I):
                    continue  # "não comprova", "does not prove": the wording we want
                found.append((n, m.group(0), sug))
                break
    return found


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = (argv if argv is not None else sys.argv[1:])
    total = 0
    for f in files:
        p = Path(f)
        if not p.is_file():
            print(f"{p}: arquivo não encontrado")
            total += 1
            continue
        for n, word, sug in lint_text(p.read_text(encoding="utf-8", errors="replace")):
            print(f"{p}:{n}: '{word}' -> {sug}")
            total += 1
    if total:
        print(f"claim_lint: {total} problema(s). Reescreva como hipótese (ou 'lint-ok: <motivo>' se for citação literal).")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
