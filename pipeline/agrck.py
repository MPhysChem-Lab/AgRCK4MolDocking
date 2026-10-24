"""agrck — single entry point of the AgRCK4MolDocking agent. Compact output on purpose (saves tokens).

  agrck doctor                         environment check (never prints secrets)
  agrck new ID                         create estudos/ID (questionario estudo.yaml + progress.md)
  agrck status [ID]                    gates + current state, one line per study
  agrck check ID E0..E6                automatic gate; needs its prerequisite gates; records the result
  agrck attempt ID TASK [--max N]      retry budget: exit 3 when exceeded -> stop and ask the user
  agrck fetch ID                       download alvo.pdb from RCSB into estudos/ID/inputs          (needs E0)
  agrck dock ID [--print]              run the docking pipeline with the parameters of estudo.yaml  (needs E1)
  agrck interactions ID                ProLIF interactions (+ ligand fragments) for every ligand   (needs E3)
  agrck diagram ID LIGAND POSE         2D diagram of one pose (prints residue <- fragment)         (needs E2)
  agrck audit ID                       metric audit (all scores side by side; metric dependence)   (needs E2)
  agrck figure ID SPEC.yaml            3D figure (open-source PyMOL; manifest; retry budget)       (needs E4)
  agrck lint FILE...                   over-claiming language check
  agrck report ID                      report pre-delivery check (+ lint, + independent review)    (needs E5)
  agrck root                           print the repository path

Gates in order: E0 questionnaire, E1 structures, E2 docking, E3 ranking, E4 interactions, E5 figures, E6 report. E0 freezes estudo.yaml (pre-registration):
editing it afterwards invalidates every gate until E0 is re-checked. Studies live in ./estudos/<ID>
of the current working directory (override: AGRCK_HOME).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
TEMPLATES = REPO / "templates"
HOME = Path(os.environ.get("AGRCK_HOME", Path.cwd()))
GATES = ["E0", "E1", "E2", "E3", "E4", "E5", "E6"]
NEEDS = {"E0": [], "E1": ["E0"], "E2": ["E1"], "E3": ["E2"], "E4": ["E3"], "E5": ["E4"], "E6": ["E5"]}
ROLES = ("serie", "controle_positivo", "cocristal")
ID_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")


class GateError(Exception):
    pass


def lig_id(name: str) -> str:
    """Same normalisation as preparation._unique_id (ids in ranking.csv)."""
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(name)).strip("_")[:40] or "lig"


def study_dir(sid: str) -> Path:
    if not ID_RX.match(sid):
        sys.exit(f"ID inválido '{sid}': use letras, números, _ ou - (sem barras)")
    d = HOME / "estudos" / sid
    if not d.exists():
        sys.exit(f"estudo '{sid}' não existe em {HOME / 'estudos'} (use: agrck new {sid})")
    return d


def load_study(sid: str) -> tuple[Path, dict]:
    d = study_dir(sid)
    return d, yaml.safe_load((d / "estudo.yaml").read_text(encoding="utf-8")) or {}


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def log_progress(d: Path, line: str) -> None:
    p = d / "progress.md"
    text = p.read_text(encoding="utf-8") if p.exists() else "# Progresso\n\n## Histórico\n"
    if "## Histórico" not in text:
        text += "\n## Histórico\n"
    p.write_text(text.rstrip() + f"\n- {now()} — {line}\n", encoding="utf-8")


# ----------------------------------------------------------------------------- gate state

def yaml_hash(d: Path) -> str:
    return hashlib.sha256((d / "estudo.yaml").read_bytes()).hexdigest()[:16]


def gate_state(d: Path) -> dict:
    f = d / ".portoes.json"
    st = json.loads(f.read_text()) if f.exists() else {}
    if st.get("E0", {}).get("ok") and st["E0"].get("yaml") != yaml_hash(d):
        st = {}                                   # pre-registration changed: everything must be re-checked
        f.write_text("{}")
        log_progress(d, "estudo.yaml mudou depois do E0: todos os portões foram invalidados")
        _sync_checkboxes(d, st)
    return st


def _dependents(gate: str) -> set[str]:
    out = {g for g, deps in NEEDS.items() if gate in deps}
    for g in list(out):
        out |= _dependents(g)
    return out


def _sync_checkboxes(d: Path, st: dict) -> None:
    p = d / "progress.md"
    if not p.exists():
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"- \[[ x]\] (E\d) ", ln)
        if m:
            lines[i] = ("- [x] " if st.get(m.group(1), {}).get("ok") else "- [ ] ") + ln[6:]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_gate(d: Path, gate: str, ok: bool) -> None:
    st = gate_state(d)
    st[gate] = {"ok": ok, "when": now(), "yaml": yaml_hash(d)}
    for g in _dependents(gate):          # any re-check of a gate invalidates what was built on it
        st.pop(g, None)
    (d / ".portoes.json").write_text(json.dumps(st, indent=1))
    _sync_checkboxes(d, st)
    log_progress(d, f"portão {gate}: {'OK' if ok else 'FALHOU'}")


def require(d: Path, *gates: str) -> None:
    st = gate_state(d)
    missing = [g for g in gates if not st.get(g, {}).get("ok")]
    if missing:
        sys.exit(f"PARE: faltam os portões {missing} (agrck check {d.name} {missing[0]}). Não pule etapas.")


def py() -> str:
    return sys.executable


def budget(s: dict) -> int:
    return int((s.get("orcamento") or {}).get("max_tentativas_por_tarefa", 2))


# ----------------------------------------------------------------------------- commands

def cmd_doctor(_a) -> int:
    ok = True

    def line(flag: bool, msg: str):
        nonlocal ok
        ok &= flag
        print(("✓ " if flag else "✗ ") + msg)
    line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}")
    for mod in ("rdkit", "yaml", "numpy", "posebusters", "prolif", "MDAnalysis", "matplotlib", "requests", "dotenv"):
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "")
            if mod == "numpy":
                line(v.startswith("1."), f"numpy {v} (o wheel do PyMOL exige numpy<2)")
            else:
                line(True, f"{mod} {v}")
        except Exception as e:  # noqa: BLE001
            line(False, f"{mod} ausente ({type(e).__name__})")
    gn = shutil.which("gnina")
    line(gn is not None, f"gnina {'em ' + gn if gn else 'não está no PATH (export PATH=$HOME/.local/bin:$PATH)'}")
    line(shutil.which("pdb2pqr") is not None or (Path(sys.executable).parent / "pdb2pqr").exists(), "pdb2pqr")
    pyml = os.environ.get("AGRCK_PYMOL_PYTHON")
    if pyml:
        r = subprocess.run([pyml, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from checks.figure_check "
                            "import pymol_is_open_source as f; o, b = f(); print(int(o), b)", str(ROOT)],
                           capture_output=True, text=True)
        flag, build = (r.stdout.strip().split(" ", 1) + [""])[:2] if r.returncode == 0 else ("0", "erro ao importar")
        oss = flag == "1"
    else:
        from checks.figure_check import pymol_is_open_source
        oss, build = pymol_is_open_source()
    line(oss, f"PyMOL para figuras: {build}")
    env_files = [os.environ.get("AGRCK_ENV_FILE"), Path.cwd() / ".env", Path.home() / ".config/agrck/.env"]
    has_key = bool(os.environ.get("NVIDIA_API_KEY"))
    for f in env_files:
        if f and Path(f).is_file():
            has_key |= any(l.startswith("NVIDIA_API_KEY=") and len(l.strip()) > 20 and "xxxx" not in l
                           for l in Path(f).read_text().splitlines())
            break
    line(has_key, "NVIDIA_API_KEY configurada (valor não exibido)" if has_key else
         "NVIDIA_API_KEY ausente: crie ~/.config/agrck/.env a partir de pipeline/.env.example (não cole a chave no chat)")
    print("doctor:", "OK" if ok else "há itens a corrigir (ver docs/INSTALACAO.md)")
    return 0 if ok else 1


def cmd_new(a) -> int:
    if not ID_RX.match(a.id):
        sys.exit(f"ID inválido '{a.id}': use letras, números, _ ou - (sem barras)")
    d = HOME / "estudos" / a.id
    if d.exists():
        print(f"estudo já existe: {d} — use 'agrck status {a.id}'")
        return 1
    for sub in ("inputs", "figuras", "relatorio"):
        (d / sub).mkdir(parents=True)
    q = (TEMPLATES / "study" / "estudo.yaml").read_text(encoding="utf-8").replace('id: ""', f'id: "{a.id}"', 1)
    (d / "estudo.yaml").write_text(q, encoding="utf-8")
    (d / "progress.md").write_text((TEMPLATES / "study" / "progress.md").read_text(encoding="utf-8")
                                   .replace("<ID>", a.id), encoding="utf-8")
    mem = HOME / "memoria"
    if not mem.exists():
        shutil.copytree(TEMPLATES / "memoria", mem)
    for f in ("AGENTS.md", "CLAUDE.md"):          # minimal always-on context in the workspace
        if not (HOME / f).exists():
            shutil.copy(TEMPLATES / "workspace" / f, HOME / f)
    log_progress(d, "estudo criado")
    print(f"criado {d}\nPróximo: preencher estudo.yaml (entrevista E0) e rodar 'agrck check {a.id} E0'")
    return 0


def cmd_status(a) -> int:
    base = HOME / "estudos"
    ids = [a.id] if a.id else (sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else [])
    if not ids:
        print("nenhum estudo (agrck new ID)")
    for sid in ids:
        d = study_dir(sid)
        st = gate_state(d)
        text = (d / "progress.md").read_text(encoding="utf-8")
        state = [l[2:] for l in text.splitlines() if l.startswith("- Etapa atual") or l.startswith("- Próximo")]
        gates = "".join("■" if st.get(g, {}).get("ok") else "□" for g in GATES)
        print(f"{sid}: {gates} (E0..E6)  " + " | ".join(state))
    return 0


def cmd_attempt(a) -> int:
    d, s = load_study(a.id)
    mx = a.max if a.max is not None else budget(s)
    f = d / ".tentativas.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    data[a.task] = data.get(a.task, 0) + 1
    f.write_text(json.dumps(data, indent=1))
    n = data[a.task]
    if n > mx:
        log_progress(d, f"limite de tentativas excedido em '{a.task}' ({mx})")
        print(f"PARE: '{a.task}' já teve {mx} tentativa(s). Mostre ao usuário o que foi feito e pergunte como seguir.")
        return 3
    print(f"tentativa {n}/{mx} de '{a.task}'")
    return 0


def ligands(s: dict) -> list[dict]:
    return [l for l in (s.get("ligantes") or []) if l.get("nome")]


def controls(s: dict) -> set[str]:
    return {lig_id(l["nome"]) for l in ligands(s) if l.get("papel") in ("controle_positivo", "cocristal")}


def _write_inputs(d: Path, s: dict) -> tuple[Path, Path]:
    alvo = s.get("alvo", {}) or {}
    pdb = str(alvo.get("pdb", "")).strip()
    src = Path(pdb) if pdb.lower().endswith(".pdb") else d / "inputs" / f"{pdb.upper()}.pdb"
    if not src.is_absolute() and not src.exists():
        src = d / src
    prot = src
    chain = str(alvo.get("cadeia") or "").strip()
    if chain and src.exists():                    # apply the declared chain to the receptor actually docked
        prot = d / "inputs" / f"{src.stem}_cadeia{chain}.pdb"
        keep = [l for l in src.read_text().splitlines()
                if not l.startswith(("ATOM", "HETATM", "ANISOU", "TER")) or (len(l) > 21 and l[21] == chain)]
        prot.write_text("\n".join(keep) + "\n")
    smi = d / "inputs" / "ligands.smi"
    smi.write_text("".join(f"{l['smiles']} {lig_id(l['nome'])}\n" for l in ligands(s) if l.get("smiles")),
                   encoding="utf-8")
    return prot, smi


def _study_config(d: Path, s: dict) -> Path:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    p = s.get("protocolo", {}) or {}
    cfg["selection"]["max_site_distance_A"] = float(p.get("max_dist_sitio_A", 12.0))
    cfg["diffdock"]["num_poses"] = int(p.get("poses", 30))
    cfg["gnina"]["minimize"] = bool(p.get("minimizar", True))
    cfg["preparation"]["keep_het"] = list((s.get("alvo", {}) or {}).get("manter_het", []) or [])
    cfg["interactions"]["ph"] = float((s.get("ensaio", {}) or {}).get("ph", 7.4))
    cfg["interactions"]["top_n"] = 0
    cfg["interactions"]["fragments"] = s.get("fragmentos") or {}
    out = d / "config.yaml"
    out.write_text("# gerado por agrck a partir de estudo.yaml — não edite à mão\n" + yaml.safe_dump(cfg, sort_keys=False,
                   allow_unicode=True), encoding="utf-8")
    return out


def cmd_fetch(a) -> int:
    import requests
    d, s = load_study(a.id)
    require(d, "E0")
    code = str(s.get("alvo", {}).get("pdb", "")).strip().upper()
    if not re.match(r"^[0-9][A-Z0-9]{3}$", code):
        sys.exit("alvo.pdb deve ser um código PDB de 4 caracteres para baixar (ou coloque o arquivo em inputs/)")
    r = requests.get(f"https://files.rcsb.org/download/{code}.pdb", timeout=60)
    r.raise_for_status()
    out = d / "inputs" / f"{code}.pdb"
    out.write_text(r.text)
    het = sorted({l[17:20].strip() for l in r.text.splitlines() if l.startswith("HETATM")} - {"HOH"})
    chains = sorted({l[21] for l in r.text.splitlines() if l.startswith("ATOM")})
    res = next((l[10:].strip() for l in r.text.splitlines() if l.startswith("REMARK   2 RESOLUTION")), "?")
    print(f"{out.name}: resolução {res}; cadeias {chains}; HETATM: {', '.join(het) or '—'}")
    log_progress(d, f"E1 baixado {code} ({res})")
    return 0


def cmd_dock(a) -> int:
    d, s = load_study(a.id)
    require(d, "E1")
    prot, smi = _write_inputs(d, s)
    cfg = _study_config(d, s)
    p = s.get("protocolo", {}) or {}
    cmd = [py(), str(ROOT / "run.py"), "--protein", str(prot), "--ligands", str(smi), "--config", str(cfg),
           "--out", str(d / "results"), "--poses", str(int(p.get("poses", 30))),
           "--ph", str((s.get("ensaio", {}) or {}).get("ph", 7.4))]
    if p.get("minimizar", True):
        cmd.append("--minimize")
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
    if a.print:
        return 0
    log_progress(d, "E2 docking iniciado")
    r = subprocess.run(cmd)
    log_progress(d, f"E2 docking terminou (exit {r.returncode})")
    return r.returncode


def cmd_interactions(a) -> int:
    d, s = load_study(a.id)
    require(d, "E3")
    cfg = _study_config(d, s)
    return subprocess.run([py(), str(ROOT / "interactions.py"), "--results", str(d / "results"),
                           "--config", str(cfg), "--top", "0"]).returncode


def _receptor_h(d: Path, s: dict) -> Path:
    ph = float((s.get("ensaio", {}) or {}).get("ph", 7.4))
    rec = d / "results" / "interactions" / f"receptor_pH{ph:g}.pdb"
    if not rec.exists():
        sys.exit(f"{rec.name} ausente: rode 'agrck interactions {d.name}' antes")
    return rec


def cmd_diagram(a) -> int:
    d, s = load_study(a.id)
    require(d, "E2")
    res = d / "results" / "poses" / lig_id(a.ligand)
    pose = res / f"pose_{int(a.pose):02d}_min.sdf"
    if not pose.exists():
        pose = res / f"pose_{int(a.pose):02d}.sdf"
    if not pose.exists():
        sys.exit(f"pose ausente: {pose} (sincronizou results/ inteiro do servidor?)")
    out = d / "figuras" / f"{lig_id(a.ligand)}_pose{int(a.pose):02d}_2d.png"
    frag = d / "results" / "interactions" / "_fragments_smarts.json"
    frag.parent.mkdir(parents=True, exist_ok=True)
    frag.write_text(json.dumps(s.get("fragmentos") or {}))
    return subprocess.run([py(), str(ROOT / "interactions_ds.py"), "--pose", str(pose), "--receptor",
                           str(_receptor_h(d, s)), "--out", str(out), "--fragments-json", str(frag),
                           "--title", f"{a.ligand} (pose {int(a.pose):02d})"]).returncode


def run_audit(d: Path, s: dict) -> int:
    p = s.get("protocolo", {}) or {}
    args = [str(d / "results"), "--primary", str(p.get("metrica_primaria", "cnn_score")),
            "--exclude", ",".join(sorted(controls(s)))]
    if p.get("composto_lider"):
        args += ["--lead", lig_id(p["composto_lider"])]
    from checks import metric_audit
    return metric_audit.main(args)


def cmd_audit(a) -> int:
    d, s = load_study(a.id)
    require(d, "E2")
    return run_audit(d, s)


def cmd_figure(a) -> int:
    d, s = load_study(a.id)
    require(d, "E4")
    task = "figura_" + Path(a.spec).stem
    if cmd_attempt(argparse.Namespace(id=a.id, task=task, max=None)) == 3:
        return 3
    pymol_py = os.environ.get("AGRCK_PYMOL_PYTHON", py())
    return subprocess.run([pymol_py, str(ROOT / "estilos" / "render_figure.py"), str(Path(a.spec).resolve())]).returncode


def cmd_root(_a) -> int:
    print(REPO)
    return 0


def cmd_lint(a) -> int:
    from checks import claim_lint
    return claim_lint.main(a.files)


def report_errors(d: Path) -> list[str]:
    from checks import claim_lint, report_check
    rel = d / "relatorio"
    docs = [p for p in list(rel.rglob("*.tex")) + list(rel.rglob("*.md")) if p.name != "REVISAO.md"]
    resumo = d / "results" / "RESUMO.md"
    if resumo.exists():
        docs.append(resumo)
    if not docs:
        return ["nenhum relatório em relatorio/ (main.tex ou .md) nem results/RESUMO.md"]
    main = "main.tex" if (rel / "main.tex").exists() else "__nenhum__.tex"
    errs = report_check.check(rel, main, [], 5.0)
    if resumo.exists():
        errs += [f"RESUMO.md:{n}: '{w}' -> {sug}" for n, w, sug in
                 claim_lint.lint_text(resumo.read_text(encoding="utf-8"))]
    rev = rel / "REVISAO.md"
    if not rev.exists():
        errs.append("relatorio/REVISAO.md ausente: rode a revisão independente (agrck-revisor) ou registre a do usuário")
    else:
        t = rev.read_text(encoding="utf-8")
        ver = re.search(r"^veredito:\s*(.+)$", t, re.M | re.I)
        if not re.search(r"^revisor:\s*\S+", t, re.M | re.I):
            errs.append("REVISAO.md sem linha 'revisor: <agrck-revisor ou nome do usuário>'")
        if not ver or not ver.group(1).strip().upper().startswith("APROVADO"):
            errs.append("REVISAO.md sem 'veredito: APROVADO' (ou APROVADO COM CORREÇÕES)")
        if re.search(r"^\s*- \[ \]", t, re.M):
            errs.append("REVISAO.md tem correções não resolvidas (- [ ])")
        newest = max(p.stat().st_mtime for p in docs)
        if rev.stat().st_mtime < newest:
            errs.append("REVISAO.md é mais antiga que o relatório: revise a versão atual")
    return errs


def cmd_report(a) -> int:
    d, _ = load_study(a.id)
    require(d, "E5")
    errs = report_errors(d)
    for e in errs:
        print("✗", e)
    print("report:", "OK (agora inspecione cada página do PDF)" if not errs else f"{len(errs)} problema(s)")
    return 1 if errs else 0


# ----------------------------------------------------------------------------- gates (return list of problems)

def _ranking(d: Path) -> list[dict]:
    f = d / "results" / "ranking.csv"
    if not f.exists():
        raise GateError("results/ranking.csv ausente (docking não terminou ou results/ não foi sincronizado)")
    return list(csv.DictReader(open(f, encoding="utf-8")))


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _local(d: Path, p: str) -> Path | None:
    """ranking paths are written relative to the run directory ('results/...' or 'results_X/...')."""
    if not p:
        return None
    q = Path(p)
    if q.is_absolute():
        return q
    return d / "results" / Path(*q.parts[1:]) if len(q.parts) > 1 else d / "results" / q


def gate_E0(d: Path, s: dict) -> list[str]:
    from checks.metric_audit import METRICS
    e = []
    alvo, p = s.get("alvo", {}) or {}, s.get("protocolo", {}) or {}
    if not alvo.get("pdb"):
        e.append("alvo.pdb vazio")
    ligs = ligands(s)
    if not ligs:
        e.append("nenhum ligante em 'ligantes'")
    ids = [lig_id(l["nome"]) for l in ligs]
    if len(set(ids)) != len(ids):
        e.append(f"nomes de ligantes colidem após normalização: {ids}")
    for l in ligs:
        if l.get("papel", "serie") not in ROLES:
            e.append(f"{l['nome']}: papel '{l.get('papel')}' inválido (use {ROLES})")
    if s.get("objetivo") != "triagem" and not any(l.get("papel") == "cocristal" for l in ligs):
        e.append("sem ligante 'cocristal' para o redocking (obrigatório, exceto em objetivo: triagem)")
    if p.get("metrica_primaria") not in METRICS:
        e.append(f"protocolo.metrica_primaria deve ser uma de {list(METRICS)} (pré-registro)")
    lead = p.get("composto_lider")
    if s.get("objetivo") == "sar" and not lead:
        e.append("objetivo SAR sem protocolo.composto_lider (necessário para a auditoria de métricas)")
    if lead and lig_id(lead) not in ids:
        e.append(f"composto_lider '{lead}' não está em 'ligantes'")
    if (s.get("ensaio", {}) or {}).get("ph") in (None, ""):
        e.append("ensaio.ph vazio")
    out = s.get("saidas", {}) or {}
    if out.get("relatorio") in ("latex", "ambos") and not out.get("instituicao"):
        e.append("saidas.instituicao vazio (cabeçalho do relatório; nunca herdar marca de outro template)")
    ex = s.get("execucao", {}) or {}
    if ex.get("onde") == "ssh" and not (ex.get("host_ssh") and ex.get("dir_remoto")):
        e.append("execucao ssh sem host_ssh/dir_remoto")
    return e


def gate_E1(d: Path, s: dict) -> list[str]:
    from rdkit import Chem
    import preparation as prep
    e = []
    prot, _ = _write_inputs(d, s)
    if not prot.exists():
        e.append(f"estrutura {prot.name} ausente em inputs/ (agrck fetch {d.name})")
    elif not any(l.startswith("ATOM") for l in prot.read_text().splitlines()):
        e.append(f"{prot.name} sem átomos da cadeia '{(s.get('alvo') or {}).get('cadeia')}'")
    basic = ("aliphatic_amine_neutral", "amidine_guanidine_neutral", "pyridine_like_N", "imidazole")
    for l in ligands(s):
        m = Chem.MolFromSmiles(l.get("smiles") or "")
        if not l.get("smiles") or m is None or m.GetNumAtoms() == 0:
            e.append(f"{l['nome']}: SMILES ausente/inválido")
            continue
        undef = [c for c in Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False)
                 if c[1] == "?"]
        if undef:
            e.append(f"{l['nome']}: {len(undef)} estereocentro(s) indefinido(s)")
        rep = prep.protonation_report(m)
        groups = rep["ionizable_groups"]
        if groups and l.get("microespecie") != "confirmada":
            e.append(f"{l['nome']}: grupos ionizáveis {groups} (carga {rep['formal_charge']:+d}) — decida a "
                     f"microespécie no pH {(s.get('ensaio') or {}).get('ph')} e marque microespecie: confirmada")
        elif rep["formal_charge"] == 0 and any(g in groups for g in basic) and not l.get("justificativa_neutro"):
            e.append(f"{l['nome']}: base possivelmente protonada no pH do ensaio mas modelada neutra — "
                     f"protone o SMILES ou preencha justificativa_neutro (pKa)")
    return e


def gate_E2(d: Path, s: dict) -> list[str]:
    rows = {r["ligand_id"]: r for r in _ranking(d)}
    e = []
    for l in ligands(s):
        lid = lig_id(l["nome"])
        r = rows.get(lid)
        if r is None:
            e.append(f"{lid}: sem linha no ranking (docking incompleto)")
        elif r.get("status") != "ok":
            e.append(f"{lid}: status '{r.get('status')}' — {(r.get('error') or '')[:120]}")
        else:
            path = _local(d, r.get("selected_pose_path") or "")
            if path is None or not path.exists():
                e.append(f"{lid}: pose selecionada ausente na cópia local — sincronize results/ inteiro")
    return e


def gate_E3(d: Path, s: dict) -> list[str]:
    e = []
    rows = _ranking(d)
    lim = float((s.get("protocolo", {}) or {}).get("max_dist_sitio_A", 12.0))
    cocrystal = {lig_id(l["nome"]) for l in ligands(s) if l.get("papel") == "cocristal"}
    for r in rows:
        lid = r["ligand_id"]
        for k in ("cnn_score", "cnn_affinity", "vina"):
            if _num(r.get(k)) is None:
                e.append(f"{lid}: {k} ausente/NaN")
        if str(r.get("posebusters_pass")).lower() != "true":
            e.append(f"{lid}: pose selecionada reprovada no PoseBusters (choque/geometria) — relate ou investigue")
        dist = _num(r.get("site_distance_A"))
        if dist is not None and dist > lim:
            e.append(f"{lid}: pose fora do sítio ({dist:.1f} Å > {lim:g} Å)")
        rmsd = _num(r.get("rmsd_to_reference"))
        if lid in cocrystal:
            if rmsd is None:
                e.append(f"redocking {lid}: sem RMSD (referência cocristalizada não pareada; confira resn/conectividade)")
            elif rmsd > 2.0:
                e.append(f"redocking {lid}: RMSD {rmsd:.2f} Å > 2 Å (protonação? seleção vs amostragem em poses.csv?)")
    rc = run_audit(d, s)
    if rc == 2:
        e.append("auditoria de métricas inválida (ver mensagem acima)")
    elif rc == 1:
        e.append("AVISO: a posição do líder depende da métrica — declare no texto (results/metric_audit.md)")
    return e


def gate_E5(d: Path, s: dict) -> list[str]:
    from checks import figure_check
    return [] if figure_check.main([str(d / "figuras")]) == 0 else ["figure_check falhou"]


def gate_E4(d: Path, s: dict) -> list[str]:
    f = d / "results" / "interactions" / "interactions.csv"
    if not f.exists():
        return [f"interactions.csv ausente (agrck interactions {d.name})"]
    header = next(csv.reader(open(f, encoding="utf-8")), [])
    if "ligand_fragment" not in header:
        return ["interactions.csv sem coluna ligand_fragment (pipeline antigo: rode agrck interactions de novo)"]
    e, per = [], {}
    for r in csv.DictReader(open(f, encoding="utf-8")):
        per.setdefault(r["ligand_id"], []).append(r)
        if r["interaction"] in ("HBDonor", "HBAcceptor") and not r.get("DHA_angle_deg"):
            e.append(f"{r['ligand_id']} {r['residue']}: ligação de H sem ângulo D–H···A")
        if not r.get("ligand_fragment"):
            e.append(f"{r['ligand_id']} {r['residue']}: interação sem fragmento")
    for row in _ranking(d):
        if row.get("status") == "ok" and row["ligand_id"] not in per:
            e.append(f"AVISO: {row['ligand_id']} sem interação tipificada — relate como achado")
    return e


def gate_E6(d: Path, s: dict) -> list[str]:
    return report_errors(d)


def cmd_check(a) -> int:
    d, s = load_study(a.id)
    require(d, *NEEDS[a.gate])
    try:
        errs = globals()[f"gate_{a.gate}"](d, s)
    except GateError as ex:
        errs = [str(ex)]
    except Exception as ex:  # noqa: BLE001  fail closed, never crash without recording
        errs = [f"erro inesperado ao avaliar {a.gate}: {type(ex).__name__}: {ex}"]
    blocking = [x for x in errs if not x.startswith("AVISO")]
    for x in errs:
        print("✗" if x in blocking else "!", x)
    ok = not blocking
    record_gate(d, a.gate, ok)
    print(f"portão {a.gate}:", "OK — mostre ao usuário e aguarde o 'ok'" if ok else "NÃO passou")
    return 0 if ok else 1


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser(prog="agrck", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(f=cmd_doctor)
    x = sub.add_parser("new"); x.add_argument("id"); x.set_defaults(f=cmd_new)
    x = sub.add_parser("status"); x.add_argument("id", nargs="?"); x.set_defaults(f=cmd_status)
    x = sub.add_parser("check"); x.add_argument("id"); x.add_argument("gate", choices=GATES); x.set_defaults(f=cmd_check)
    x = sub.add_parser("attempt"); x.add_argument("id"); x.add_argument("task"); x.add_argument("--max", type=int)
    x.set_defaults(f=cmd_attempt)
    x = sub.add_parser("fetch"); x.add_argument("id"); x.set_defaults(f=cmd_fetch)
    x = sub.add_parser("dock"); x.add_argument("id"); x.add_argument("--print", action="store_true"); x.set_defaults(f=cmd_dock)
    x = sub.add_parser("interactions"); x.add_argument("id"); x.set_defaults(f=cmd_interactions)
    x = sub.add_parser("diagram"); x.add_argument("id"); x.add_argument("ligand"); x.add_argument("pose")
    x.set_defaults(f=cmd_diagram)
    x = sub.add_parser("audit"); x.add_argument("id"); x.set_defaults(f=cmd_audit)
    x = sub.add_parser("figure"); x.add_argument("id"); x.add_argument("spec"); x.set_defaults(f=cmd_figure)
    x = sub.add_parser("lint"); x.add_argument("files", nargs="+"); x.set_defaults(f=cmd_lint)
    x = sub.add_parser("report"); x.add_argument("id"); x.set_defaults(f=cmd_report)
    sub.add_parser("root").set_defaults(f=cmd_root)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
