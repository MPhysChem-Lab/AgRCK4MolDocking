#!/usr/bin/env python3
"""specboard — estado de projeto Spec-Driven Modular + painel de validação.

Uso (rodar na raiz do projeto; funciona em PowerShell):
  python specboard.py init                 cria .specboard/estado.json de exemplo
  python specboard.py validate             checa regras
  python specboard.py lock <MOD>           trava o contrato do módulo (pré-registro)
  python specboard.py amend <MOD> -j "..." registra emenda em contrato travado
  python specboard.py queue                fila de revisão por impacto
  python specboard.py build [--open]       gera .specboard/painel.html
  python specboard.py review <ETAPA>       HUMANO: marca como revisado
  python specboard.py verify <ETAPA>       HUMANO: marca como verificado

review/verify exigem terminal interativo e confirmação digitada.
Agentes NÃO devem executá-los (o hook block_verify_hook.py bloqueia).
"""
import argparse, hashlib, json, os, sys, webbrowser
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "assets" / "painel_template.html"
EXEMPLO = SKILL_DIR / "assets" / "estado_exemplo.json"

STATUS_AGENTE = {"pendente", "em_curso", "executado", "bloqueado"}
IMPACTOS = {"alto": 0, "medio": 1, "baixo": 2}


def paths(base):
    d = Path(base) / ".specboard"
    return d, d / "estado.json", d / "verificacoes.jsonl", d / "painel.html"


def load(base):
    d, est, ver, _ = paths(base)
    if not est.exists():
        sys.exit(f"Não encontrei {est}. Rode: python specboard.py init")
    estado = json.loads(est.read_text(encoding="utf-8"))
    regs = []
    if ver.exists():
        for ln in ver.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                regs.append(json.loads(ln))
    return estado, regs


def save(base, estado):
    _, est, _, _ = paths(base)
    estado.setdefault("projeto", {})["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    est.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def h(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def hash_contrato(mod):
    c = {k: v for k, v in (mod.get("contrato") or {}).items() if k not in ("travado_em", "hash")}
    return h(c)


def hash_etapa(et):
    return h({k: et.get(k) for k in ("titulo", "afirmacao", "verificacao", "evidencia")})


def etapas(estado):
    for m in estado.get("modulos", []):
        for e in m.get("etapas", []):
            yield m, e


def status_efetivo(et, regs):
    """Combina status do agente com registros humanos. Verificação expira se a etapa mudou."""
    atual = hash_etapa(et)
    niveis = [r for r in regs if r["etapa"] == et["id"]]
    if any(r["nivel"] == "verificado" and r["hash_etapa"] == atual for r in niveis):
        return "verificado", None
    if any(r["nivel"] == "revisado" and r["hash_etapa"] == atual for r in niveis):
        return "revisado", None
    expirou = any(r["hash_etapa"] != atual for r in niveis)
    return et.get("status", "pendente"), ("expirada" if expirou else None)


def validar(estado, regs):
    erros, avisos = [], []
    p = estado.get("projeto", {})
    if not p.get("pergunta_central"):
        erros.append("projeto.pergunta_central vazia: o painel precisa saber o que está sendo respondido.")
    ids_mod = [m.get("id") for m in estado.get("modulos", [])]
    if len(ids_mod) != len(set(ids_mod)):
        erros.append("IDs de módulo duplicados.")
    if not any(m.get("resultado_final") for m in estado.get("modulos", [])):
        avisos.append("Nenhum módulo marcado com resultado_final: true.")
    vistos = set()
    for m in estado.get("modulos", []):
        for dep in m.get("depende_de", []):
            if dep not in ids_mod:
                erros.append(f"{m['id']}: depende de módulo inexistente '{dep}'.")
        c = m.get("contrato") or {}
        if c.get("hash") and c["hash"] != hash_contrato(m):
            erros.append(f"{m['id']}: contrato travado foi alterado sem emenda. Rode: amend {m['id']} -j \"motivo\"")
        if not m.get("etapas") and not m.get("etapas_estimadas"):
            avisos.append(f"{m['id']}: sem etapas nem etapas_estimadas; fica fora do denominador.")
        for e in m.get("etapas", []):
            if e["id"] in vistos:
                erros.append(f"Etapa duplicada: {e['id']}")
            vistos.add(e["id"])
            st = e.get("status", "pendente")
            if st not in STATUS_AGENTE:
                erros.append(f"{e['id']}: status '{st}' inválido no estado.json. "
                             "'revisado'/'verificado' só existem via comando humano.")
            if e.get("impacto") not in IMPACTOS:
                erros.append(f"{e['id']}: impacto deve ser alto/medio/baixo.")
            if st == "executado" and not (e.get("afirmacao") and e.get("verificacao")):
                erros.append(f"{e['id']}: executado sem 'afirmacao' e 'verificacao' — nada a validar.")
            if st == "executado" and not e.get("evidencia"):
                avisos.append(f"{e['id']}: executado sem evidência apontada.")
    return erros, avisos


def resumo(estado, regs):
    total = feitos = 0
    estimado = False
    cont = {}
    for m in estado.get("modulos", []):
        if m.get("etapas"):
            total += len(m["etapas"])
        elif m.get("etapas_estimadas"):
            total += int(m["etapas_estimadas"]); estimado = True
        for e in m.get("etapas", []):
            s, _ = status_efetivo(e, regs)
            cont[s] = cont.get(s, 0) + 1
            feitos += s == "verificado"
    return {"total": total, "verificadas": feitos, "estimado": estimado, "contagem": cont}


def fila(estado, regs):
    itens = []
    for m, e in etapas(estado):
        s, exp = status_efetivo(e, regs)
        if s in ("executado", "revisado"):
            itens.append((IMPACTOS.get(e.get("impacto"), 3), 0 if m.get("resultado_final") else 1,
                          e["id"], e["titulo"], e.get("impacto"), s, exp, e.get("revisao", "completa")))
    return sorted(itens)


def cmd_init(a):
    d, est, _, _ = paths(a.dir)
    if est.exists():
        sys.exit(f"{est} já existe.")
    d.mkdir(exist_ok=True)
    est.write_text(EXEMPLO.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Criado {est}. Edite a partir do plano do projeto.")


def cmd_validate(a):
    estado, regs = load(a.dir)
    erros, avisos = validar(estado, regs)
    for x in avisos: print("AVISO:", x)
    for x in erros: print("ERRO: ", x)
    if erros:
        sys.exit(1)
    print("OK — estado válido.")


def achar_mod(estado, mid):
    for m in estado.get("modulos", []):
        if m["id"] == mid:
            return m
    sys.exit(f"Módulo {mid} não existe.")


def cmd_lock(a):
    estado, _ = load(a.dir)
    m = achar_mod(estado, a.modulo)
    c = m.setdefault("contrato", {})
    if c.get("hash"):
        sys.exit("Contrato já travado. Mudanças agora exigem 'amend'.")
    faltam = [k for k in ("pergunta", "criterios_aceitacao", "criterio_abandono") if not c.get(k)]
    if faltam:
        sys.exit(f"Contrato incompleto, falta: {', '.join(faltam)}")
    c["travado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    c["hash"] = hash_contrato(m)
    save(a.dir, estado)
    print(f"{m['id']} travado (hash {c['hash']}).")


def cmd_amend(a):
    estado, _ = load(a.dir)
    m = achar_mod(estado, a.modulo)
    c = m.get("contrato") or {}
    if not c.get("hash"):
        sys.exit("Contrato não está travado; edite livremente.")
    novo = hash_contrato(m)
    if novo == c["hash"]:
        sys.exit("Nada mudou no contrato.")
    m.setdefault("emendas", []).append({
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"), "hash_anterior": c["hash"],
        "hash_novo": novo, "justificativa": a.justificativa})
    c["hash"] = novo
    save(a.dir, estado)
    print(f"Emenda registrada em {m['id']}. Ela aparece em destaque no painel.")


def cmd_queue(a):
    estado, regs = load(a.dir)
    itens = fila(estado, regs)
    if not itens:
        print("Fila vazia."); return
    for _, _, eid, tit, imp, s, exp, rev in itens:
        extra = " [verificação expirada]" if exp else ""
        print(f"{eid:<10} {imp:<6} {s:<10} {rev:<10} {tit}{extra}")


def cmd_humano(a, nivel):
    if not sys.stdin.isatty() or os.environ.get("CLAUDECODE"):
        sys.exit("Recusado: este comando só roda em terminal interativo humano.")
    estado, regs = load(a.dir)
    alvo = next((e for _, e in etapas(estado) if e["id"] == a.etapa), None)
    if not alvo:
        sys.exit(f"Etapa {a.etapa} não existe.")
    print(f"\n{alvo['id']} — {alvo['titulo']}")
    print(f"  Afirmação:   {alvo.get('afirmacao')}")
    print(f"  Verificação: {alvo.get('verificacao')}")
    print(f"  Evidência:   {', '.join(alvo.get('evidencia', [])) or '(nenhuma)'}\n")
    if nivel == "verificado":
        print("Verificado = você conferiu a evidência, não só leu o resumo.")
    if input(f"Digite o ID da etapa para confirmar '{nivel}': ").strip() != alvo["id"]:
        sys.exit("Cancelado.")
    revisor = input("Seu nome/iniciais: ").strip()
    nota = input("Nota (o que você conferiu): ").strip()
    if not revisor or (nivel == "verificado" and not nota):
        sys.exit("Cancelado: revisor e nota são obrigatórios.")
    _, _, ver, _ = paths(a.dir)
    with ver.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"etapa": alvo["id"], "nivel": nivel, "revisor": revisor, "nota": nota,
                            "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "hash_etapa": hash_etapa(alvo)}, ensure_ascii=False) + "\n")
    print(f"Registrado: {alvo['id']} {nivel}. Rode 'build' para atualizar o painel.")


def cmd_build(a):
    estado, regs = load(a.dir)
    erros, avisos = validar(estado, regs)
    for m in estado.get("modulos", []):
        for e in m.get("etapas", []):
            e["_status"], e["_exp"] = status_efetivo(e, regs)
            e["_regs"] = [r for r in regs if r["etapa"] == e["id"]]
        m["_contrato_ok"] = not ((m.get("contrato") or {}).get("hash") and
                                 m["contrato"]["hash"] != hash_contrato(m))
    payload = {"estado": estado, "resumo": resumo(estado, regs),
               "fila": [dict(zip(["_", "__", "id", "titulo", "impacto", "status", "exp", "revisao"], f))
                        for f in fila(estado, regs)],
               "erros": erros, "avisos": avisos,
               "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DADOS__*/null", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    _, _, _, out = paths(a.dir)
    out.write_text(html, encoding="utf-8")
    print(f"Painel gerado: {out}" + (f"  ({len(erros)} erro(s) exibidos no topo)" if erros else ""))
    if a.open:
        webbrowser.open(out.resolve().as_uri())


def main():
    p = argparse.ArgumentParser(description="specboard")
    p.add_argument("--dir", default=".", help="raiz do projeto")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init"); sub.add_parser("validate"); sub.add_parser("queue")
    b = sub.add_parser("build"); b.add_argument("--open", action="store_true")
    for n in ("lock",):
        sub.add_parser(n).add_argument("modulo")
    am = sub.add_parser("amend"); am.add_argument("modulo"); am.add_argument("-j", "--justificativa", required=True)
    for n in ("review", "verify"):
        sub.add_parser(n).add_argument("etapa")
    a = p.parse_args()
    {"init": cmd_init, "validate": cmd_validate, "lock": cmd_lock, "amend": cmd_amend,
     "queue": cmd_queue, "build": cmd_build,
     "review": lambda a: cmd_humano(a, "revisado"),
     "verify": lambda a: cmd_humano(a, "verificado")}[a.cmd](a)


if __name__ == "__main__":
    main()
