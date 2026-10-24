"""Read-only progress board (specboard renderer) for an AgRCK study.

The board is a VIEW of the study state: estudo.yaml + .portoes.json + files on disk -> .specboard/estado.json
-> .specboard/painel.html. It is regenerated after every gate change; nothing on it is a lock or a gate, and
editing or deleting it changes nothing in the study. Renderer: vendor/specboard (Apache-2.0).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "vendor" / "specboard" / "scripts" / "specboard.py"

# gate -> (module title, phase, impact, what the human should look at, evidence paths relative to the study)
STAGES = [
    ("E0", "Questionário e pré-registro", "Planejamento", "medio",
     "Abrir estudo.yaml: alvo, ligantes, pH, controles, métrica primária e composto líder conferem com o ensaio.",
     ["estudo.yaml"]),
    ("E1", "Estruturas e microespécies", "Preparação", "alto",
     "Abrir inputs/: cadeia certa, cofatores mantidos, SMILES com estereoquímica e protonação no pH do ensaio.",
     ["inputs/"]),
    ("E2", "Docking (DiffDock + GNINA + PoseBusters)", "Docking", "medio",
     "Todos os ligantes têm linha em results/ranking.csv com status ok e pose local.",
     ["results/ranking.csv"]),
    ("E3", "Ranking auditado", "Análise", "alto",
     "Abrir results/metric_audit.md: redocking ≤ 2 Å, poses no sítio, todas as métricas e a primária pré-registrada.",
     ["results/metric_audit.md", "results/ranking.csv"]),
    ("E4", "Interações ProLIF por fragmento", "Análise", "alto",
     "Abrir results/interactions/interactions.csv: cada interação citada tem tipo, distância, ângulo e fragmento.",
     ["results/interactions/interactions.csv"]),
    ("E5", "Figuras 3D", "Entrega", "baixo",
     "Abrir figuras/: todos os objetos da legenda visíveis; manifesto open-source.",
     ["figuras/figuras_manifest.json"]),
    ("E6", "Relatório revisado", "Entrega", "alto",
     "Ler o relatório e relatorio/REVISAO.md: números conferem com os CSVs, linguagem de hipótese, limitações.",
     ["relatorio/", "relatorio/REVISAO.md"]),
]


def estado(d: Path, s: dict, gates: dict) -> dict:
    alvo = (s.get("alvo") or {})
    p = (s.get("protocolo") or {})
    lead = p.get("composto_lider") or "o composto mais ativo"
    pergunta = s.get("pergunta_central") or (
        f"Que modo de ligação em {alvo.get('nome') or alvo.get('pdb') or 'o alvo'} explica a atividade de {lead} "
        f"frente aos análogos?")
    modulos, current = [], None
    for i, (g, title, fase, imp, verif, evid) in enumerate(STAGES):
        st = gates.get(g, {})
        if st.get("ok"):
            status = "executado"
        elif st and not st.get("ok"):
            status = "bloqueado"
        elif current is None:
            status = "em_curso" if all(gates.get(x, {}).get("ok") for x, *_ in STAGES[:i]) else "pendente"
        else:
            status = "pendente"
        if status in ("em_curso", "bloqueado") and current is None:
            current = f"M{i}.1"
        when = f" em {st['when']}" if st.get("when") else ""
        afirma = {"executado": f"agrck check {g} aprovado{when}",
                  "bloqueado": f"agrck check {g} NÃO passou{when} (ver progress.md)",
                  "em_curso": f"etapa {g} em andamento", "pendente": f"etapa {g} ainda não iniciada"}[status]
        etapa = {"id": f"M{i}.1", "titulo": f"Portão {g}: {title}", "status": status, "impacto": imp,
                 "afirmacao": afirma, "verificacao": verif,
                 "evidencia": [e for e in evid if (d / e).exists()] or evid,
                 "quem": "agrck check (automático)" if status == "executado" else "agente"}
        if st.get("when"):
            etapa["data"] = st["when"][:10]
        mod = {"id": f"M{i}", "titulo": title, "fase": fase, "depende_de": [f"M{i - 1}"] if i else [],
               "objetivo": verif, "etapas": [etapa]}
        if g == "E0":
            mod["contrato"] = {"pergunta": "Pré-registro do estudo (congelado pelo agrck no E0)",
                               "criterios_aceitacao": ["Redocking do cocristal ≤ 2 Å",
                                                       "Conclusões pela métrica primária pré-registrada"],
                               "criterio_abandono": "Redocking > 2 Å sem explicação: rever alvo/protonação.",
                               "parametros": {k: p.get(k) for k in ("metrica_primaria", "composto_lider",
                                                                     "poses", "max_dist_sitio_A")}}
        if g == "E6":
            mod["resultado_final"] = True
        modulos.append(mod)
    proj = {"nome": s.get("id") or d.name, "titulo": f"Estudo de docking — {s.get('id') or d.name}",
            "subtitulo": f"Alvo {alvo.get('pdb', '?')} · pH {(s.get('ensaio') or {}).get('ph', '?')} · "
                         f"{len(s.get('ligantes') or [])} ligantes · painel só de visualização "
                         f"(verificado = portão do agrck aprovado)",
            "pergunta_central": pergunta,
            "glossario": [["RMSD", "desvio da pose em relação ao cristal (≤ 2 Å = protocolo reproduz o cristal)"],
                          ["CNNscore", "confiança da rede de que a pose está correta (0–1)"],
                          ["Vina", "escore empírico em kcal/mol; não é ΔG experimental"],
                          ["ProLIF", "interações tipificadas por distância e ângulo"]],
            "fontes": ["estudo.yaml", ".portoes.json (agrck check)"]}
    if current:
        proj["voce_esta_aqui"] = current
    return {"projeto": proj, "fases": ["Planejamento", "Preparação", "Docking", "Análise", "Entrega"],
            "modulos": modulos}


def build(d: Path, s: dict, open_browser: bool = False) -> Path | None:
    """Write .specboard/estado.json and render painel.html. Never raises: the board is optional."""
    try:
        gates = json.loads((d / ".portoes.json").read_text()) if (d / ".portoes.json").exists() else {}
        sb = d / ".specboard"
        sb.mkdir(exist_ok=True)
        est = estado(d, s, gates)
        (sb / "estado.json").write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
        # mirror approved gates as the panel's "verified" records (derived view, rewritten on every refresh)
        sys.path.insert(0, str(RENDERER.parent))
        from specboard import hash_etapa
        regs = [{"etapa": e["id"], "nivel": "verificado", "revisor": "agrck check (portão automático)",
                 "nota": e["afirmacao"], "data": gates[g].get("when", ""), "hash_etapa": hash_etapa(e)}
                for m, (g, *_) in zip(est["modulos"], STAGES) for e in m["etapas"]
                if gates.get(g, {}).get("ok")]
        (sb / "verificacoes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in regs),
                                               encoding="utf-8")
        cmd = [sys.executable, str(RENDERER), "--dir", str(d), "build"] + (["--open"] if open_browser else [])
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return sb / "painel.html" if r.returncode == 0 else None
    except Exception:  # noqa: BLE001  visualization must never break the workflow
        return None
