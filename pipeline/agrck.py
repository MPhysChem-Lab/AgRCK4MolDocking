"""agrck — single entry point of the AgRCK4MolDocking agent. Compact output on purpose (saves tokens).

  agrck doctor                         environment check (never prints secrets)
  agrck new ID                         create estudos/ID (questionario estudo.yaml + progress.md)
  agrck status [ID]                    3-line summary + gates
  agrck check ID E0..E6                automatic gate for a stage; records the result in progress.md
  agrck attempt ID TASK [--max N]      retry budget: exit 3 when exceeded -> stop and ask the user
  agrck fetch ID                       download alvo.pdb from RCSB into estudos/ID/inputs
  agrck dock ID [--print]              run the docking pipeline with the parameters of estudo.yaml
  agrck interactions ID                ProLIF interactions (+ ligand fragments) for every ligand
  agrck diagram ID LIGAND POSE         2D diagram of one pose (prints residue <- fragment)
  agrck audit ID                       metric audit (all scores side by side; metric dependence)
  agrck lint FILE...                   over-claiming language check
  agrck figure ID SPEC.yaml            3D figure (open-source PyMOL; manifest; retry budget)
  agrck report ID                      report pre-delivery check (+ lint)
  agrck root                           print the repository path

Studies live in ./estudos/<ID> of the current working directory (override: AGRCK_HOME).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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


def study_dir(sid: str) -> Path:
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


def mark_gate(d: Path, gate: str, ok: bool) -> None:
    p = d / "progress.md"
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(f"- [") and f"] {gate} " in ln:
            lines[i] = ("- [x] " if ok else "- [ ] ") + ln[6:]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_progress(d, f"portão {gate}: {'OK' if ok else 'FALHOU'}")


def py() -> str:
    return sys.executable


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
    from checks.figure_check import pymol_is_open_source
    oss, build = pymol_is_open_source()
    line(oss, f"PyMOL para figuras: {build}")
    env_files = [os.environ.get("AGRCK_ENV_FILE"), Path.cwd() / ".env", Path.home() / ".config/agrck/.env"]
    has_key = False
    for f in env_files:
        if f and Path(f).is_file():
            has_key = any(l.startswith("NVIDIA_API_KEY=") and len(l.strip()) > 20 and "xxxx" not in l
                          for l in Path(f).read_text().splitlines())
            break
    line(has_key or bool(os.environ.get("NVIDIA_API_KEY")),
         "NVIDIA_API_KEY configurada (valor não exibido)" if has_key or os.environ.get("NVIDIA_API_KEY")
         else "NVIDIA_API_KEY ausente: crie .env a partir de pipeline/.env.example (não cole a chave no chat)")
    print("doctor:", "OK" if ok else "há itens a corrigir (ver docs/INSTALACAO.md)")
    return 0 if ok else 1


def cmd_new(a) -> int:
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
            shutil.copy(REPO / f, HOME / f)
    log_progress(d, "estudo criado")
    print(f"criado {d}\nPróximo: preencher estudo.yaml (entrevista E0) e rodar 'agrck check {a.id} E0'")
    return 0


def cmd_status(a) -> int:
    base = HOME / "estudos"
    ids = [a.id] if a.id else sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []
    if not ids:
        print("nenhum estudo (agrck new ID)")
    for sid in ids:
        text = (base / sid / "progress.md").read_text(encoding="utf-8")
        state = [l for l in text.splitlines() if l.startswith("- Etapa atual") or l.startswith("- Próximo")]
        gates = "".join("■" if f"- [x] {g} " in text else "□" for g in GATES)
        print(f"{sid}: {gates} (E0..E6)  " + " | ".join(s[2:] for s in state))
    return 0


def cmd_attempt(a) -> int:
    d = study_dir(a.id)
    f = d / ".tentativas.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    data[a.task] = data.get(a.task, 0) + 1
    f.write_text(json.dumps(data, indent=1))
    n = data[a.task]
    if n > a.max:
        log_progress(d, f"limite de tentativas excedido em '{a.task}' ({n - 1}/{a.max})")
        print(f"PARE: '{a.task}' já teve {a.max} tentativa(s). Mostre ao usuário o que foi feito e pergunte como seguir.")
        return 3
    print(f"tentativa {n}/{a.max} de '{a.task}'")
    return 0


def _write_inputs(d: Path, s: dict) -> tuple[Path, Path]:
    alvo = s.get("alvo", {})
    pdb = str(alvo.get("pdb", "")).strip()
    prot = Path(pdb) if pdb.endswith(".pdb") else d / "inputs" / f"{pdb}.pdb"
    if not prot.is_absolute():
        prot = d / prot if not prot.exists() else prot
    smi = d / "inputs" / "ligands.smi"
    ligs = [l for l in s.get("ligantes", []) if l.get("smiles")]
    if ligs:
        smi.write_text("".join(f"{l['smiles']} {l['nome']}\n" for l in ligs), encoding="utf-8")
    return prot, smi


def _study_config(d: Path, s: dict) -> Path:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    p = s.get("protocolo", {})
    cfg["selection"]["max_site_distance_A"] = float(p.get("max_dist_sitio_A", 12.0))
    cfg["diffdock"]["num_poses"] = int(p.get("poses", 30))
    cfg["gnina"]["minimize"] = bool(p.get("minimizar", True))
    cfg["preparation"]["keep_het"] = list(s.get("alvo", {}).get("manter_het", []) or [])
    cfg["interactions"]["ph"] = float(s.get("ensaio", {}).get("ph", 7.4))
    cfg["interactions"]["top_n"] = 0
    cfg["interactions"]["fragments"] = s.get("fragmentos") or {}
    out = d / "config.yaml"
    out.write_text("# gerado por agrck a partir de estudo.yaml — não edite à mão\n" + yaml.safe_dump(cfg, sort_keys=False,
                   allow_unicode=True), encoding="utf-8")
    return out


def cmd_dock(a) -> int:
    d, s = load_study(a.id)
    prot, smi = _write_inputs(d, s)
    cfg = _study_config(d, s)
    p = s.get("protocolo", {})
    cmd = [py(), str(ROOT / "run.py"), "--protein", str(prot), "--ligands", str(smi), "--config", str(cfg),
           "--out", str(d / "results"), "--poses", str(int(p.get("poses", 30))),
           "--ph", str(s.get("ensaio", {}).get("ph", 7.4))]
    if p.get("minimizar", True):
        cmd.append("--minimize")
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
    if a.print:
        return 0
    log_progress(d, "E2 docking iniciado")
    r = subprocess.run(cmd)
    log_progress(d, f"E2 docking terminou (exit {r.returncode})")
    return r.returncode


def cmd_fetch(a) -> int:
    import requests
    d, s = load_study(a.id)
    code = str(s.get("alvo", {}).get("pdb", "")).strip().upper()
    if not code or code.endswith(".PDB"):
        sys.exit("alvo.pdb deve ser um código PDB de 4 caracteres para baixar (ou coloque o arquivo em inputs/)")
    r = requests.get(f"https://files.rcsb.org/download/{code}.pdb", timeout=60)
    r.raise_for_status()
    out = d / "inputs" / f"{code}.pdb"
    out.write_text(r.text)
    het = sorted({l[17:20].strip() for l in r.text.splitlines() if l.startswith("HETATM")} - {"HOH"})
    res = next((l[10:].strip() for l in r.text.splitlines() if l.startswith("REMARK   2 RESOLUTION")), "?")
    print(f"{out.name}: resolução {res}; HETATM: {', '.join(het) or '—'}")
    log_progress(d, f"E1 baixado {code} ({res})")
    return 0


def cmd_figure(a) -> int:
    d, _ = load_study(a.id)
    task = "figura_" + Path(a.spec).stem
    if cmd_attempt(argparse.Namespace(id=a.id, task=task, max=2)) == 3:
        return 3
    pymol_py = os.environ.get("AGRCK_PYMOL_PYTHON", py())
    r = subprocess.run([pymol_py, str(ROOT / "estilos" / "render_figure.py"), str(Path(a.spec).resolve())])
    return r.returncode


def cmd_root(_a) -> int:
    print(REPO)
    return 0


def cmd_interactions(a) -> int:
    d, s = load_study(a.id)
    cfg = _study_config(d, s)
    return subprocess.run([py(), str(ROOT / "interactions.py"), "--results", str(d / "results"),
                           "--config", str(cfg), "--top", "0"]).returncode


def cmd_diagram(a) -> int:
    d, s = load_study(a.id)
    res = d / "results"
    pose = res / "poses" / a.ligand / f"pose_{int(a.pose):02d}_min.sdf"
    if not pose.exists():
        pose = res / "poses" / a.ligand / f"pose_{int(a.pose):02d}.sdf"
    rec = next((res / "interactions").glob("receptor_pH*.pdb"), None)
    if rec is None:
        sys.exit("receptor protonado ausente: rode 'agrck interactions ID' antes")
    out = d / "figuras" / f"{a.ligand}_pose{int(a.pose):02d}_2d.png"
    return subprocess.run([py(), str(ROOT / "interactions_ds.py"), "--pose", str(pose), "--receptor", str(rec),
                           "--out", str(out), "--title", f"{a.ligand} (pose {int(a.pose):02d})"]).returncode


def cmd_audit(a) -> int:
    d, s = load_study(a.id)
    p = s.get("protocolo", {})
    args = [str(d / "results"), "--primary", p.get("metrica_primaria", "cnn_score")]
    if p.get("composto_lider"):
        args += ["--lead", p["composto_lider"]]
    from checks import metric_audit
    return metric_audit.main(args)


def cmd_lint(a) -> int:
    from checks import claim_lint
    return claim_lint.main(a.files)


def cmd_report(a) -> int:
    d, _ = load_study(a.id)
    from checks import claim_lint, report_check
    rc = report_check.main([str(d / "relatorio")])
    resumo = d / "results" / "RESUMO.md"
    return rc | (claim_lint.main([str(resumo)]) if resumo.exists() else 0)


# ----------------------------------------------------------------------------- gates

def gate_E0(d: Path, s: dict) -> list[str]:
    e = []
    alvo, p = s.get("alvo", {}), s.get("protocolo", {})
    if not alvo.get("pdb"):
        e.append("alvo.pdb vazio")
    ligs = s.get("ligantes") or []
    if not [l for l in ligs if l.get("nome")]:
        e.append("nenhum ligante em 'ligantes'")
    if not [l for l in ligs if l.get("papel") in ("controle_positivo", "cocristal")]:
        e.append("sem controle (cocristal para redocking e/ou controle positivo do ensaio)")
    if not p.get("metrica_primaria"):
        e.append("protocolo.metrica_primaria não pré-registrada")
    if s.get("objetivo") == "sar" and not p.get("composto_lider"):
        e.append("objetivo SAR sem protocolo.composto_lider (necessário para a auditoria de métricas)")
    if s.get("ensaio", {}).get("ph") in (None, ""):
        e.append("ensaio.ph vazio")
    return e


def gate_E1(d: Path, s: dict) -> list[str]:
    from rdkit import Chem
    import preparation as prep
    e = []
    prot, _ = _write_inputs(d, s)
    if not prot.exists():
        e.append(f"estrutura {prot.name} ausente em inputs/")
    for l in s.get("ligantes") or []:
        m = Chem.MolFromSmiles(l.get("smiles") or "")
        if m is None:
            e.append(f"{l.get('nome')}: SMILES ausente/inválido")
            continue
        undef = [c for c in Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False)
                 if c[1] == "?"]
        if undef:
            e.append(f"{l['nome']}: {len(undef)} estereocentro(s) indefinido(s)")
        rep = prep.protonation_report(m)
        if rep["ionizable_groups"] and l.get("microespecie") != "confirmada":
            e.append(f"{l['nome']}: grupos ionizáveis {rep['ionizable_groups']} (carga {rep['formal_charge']:+d}) — "
                     f"defina a microespécie no pH {s.get('ensaio', {}).get('ph')} e marque microespecie: confirmada")
    return e


def gate_E2(d: Path, s: dict) -> list[str]:
    r = d / "results" / "ranking.csv"
    return [] if r.exists() else ["results/ranking.csv ausente (docking não terminou?)"]


def gate_E3(d: Path, s: dict) -> list[str]:
    import csv
    e = []
    rows = list(csv.DictReader(open(d / "results" / "ranking.csv", encoding="utf-8")))
    lim = float(s.get("protocolo", {}).get("max_dist_sitio_A", 12.0))
    for r in rows:
        rmsd = r.get("rmsd_to_reference")
        if rmsd not in (None, "") and float(rmsd) > 2.0:
            e.append(f"redocking {r['ligand_id']}: RMSD {float(rmsd):.2f} Å > 2 Å (protonação? seleção vs amostragem?)")
        dist = r.get("site_distance_A")
        if dist not in (None, "") and float(dist) > lim:
            e.append(f"{r['ligand_id']}: pose fora do sítio ({float(dist):.1f} Å > {lim:g} Å)")
    if not any(r.get("rmsd_to_reference") not in (None, "") for r in rows):
        e.append("nenhum RMSD de redocking: inclua o ligante cocristalizado na série")
    if cmd_audit(argparse.Namespace(id=d.name)) != 0:
        e.append("auditoria de métricas: conclusão depende da métrica (ver results/metric_audit.md) — relate todas")
    return e


def gate_E4(d: Path, s: dict) -> list[str]:
    from checks import figure_check
    return [] if figure_check.main([str(d / "figuras")]) == 0 else ["figure_check falhou"]


def gate_E5(d: Path, s: dict) -> list[str]:
    f = d / "results" / "interactions" / "interactions.csv"
    if not f.exists():
        return ["interactions.csv ausente (agrck interactions ID)"]
    head = f.read_text(encoding="utf-8").splitlines()[0]
    return [] if "ligand_fragment" in head else ["interactions.csv sem coluna ligand_fragment (pipeline antigo)"]


def gate_E6(d: Path, s: dict) -> list[str]:
    return [] if cmd_report(argparse.Namespace(id=d.name)) == 0 else ["relatório com problemas (ver acima)"]


def cmd_check(a) -> int:
    d, s = load_study(a.id)
    errs = globals()[f"gate_{a.gate}"](d, s)
    for x in errs:
        print("✗", x)
    ok = not errs
    if a.gate == "E3" and errs and all(x.startswith("auditoria") for x in errs):
        ok = True   # metric dependence is reported, not blocking: it must be stated in the text
        print("(aviso não bloqueante: declare no texto que a conclusão depende da métrica)")
    mark_gate(d, a.gate, ok)
    print(f"portão {a.gate}:", "OK — mostre ao usuário e aguarde o 'ok'" if ok else "NÃO passou")
    return 0 if ok else 1


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser(prog="agrck", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(f=cmd_doctor)
    x = sub.add_parser("new"); x.add_argument("id"); x.set_defaults(f=cmd_new)
    x = sub.add_parser("status"); x.add_argument("id", nargs="?"); x.set_defaults(f=cmd_status)
    x = sub.add_parser("check"); x.add_argument("id"); x.add_argument("gate", choices=GATES); x.set_defaults(f=cmd_check)
    x = sub.add_parser("attempt"); x.add_argument("id"); x.add_argument("task"); x.add_argument("--max", type=int, default=2)
    x.set_defaults(f=cmd_attempt)
    x = sub.add_parser("dock"); x.add_argument("id"); x.add_argument("--print", action="store_true"); x.set_defaults(f=cmd_dock)
    x = sub.add_parser("interactions"); x.add_argument("id"); x.set_defaults(f=cmd_interactions)
    x = sub.add_parser("diagram"); x.add_argument("id"); x.add_argument("ligand"); x.add_argument("pose")
    x.set_defaults(f=cmd_diagram)
    x = sub.add_parser("audit"); x.add_argument("id"); x.set_defaults(f=cmd_audit)
    x = sub.add_parser("lint"); x.add_argument("files", nargs="+"); x.set_defaults(f=cmd_lint)
    x = sub.add_parser("report"); x.add_argument("id"); x.set_defaults(f=cmd_report)
    x = sub.add_parser("fetch"); x.add_argument("id"); x.set_defaults(f=cmd_fetch)
    x = sub.add_parser("figure"); x.add_argument("id"); x.add_argument("spec"); x.set_defaults(f=cmd_figure)
    sub.add_parser("root").set_defaults(f=cmd_root)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
