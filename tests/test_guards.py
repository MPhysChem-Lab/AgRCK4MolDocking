"""Deterministic guards. Each lesson in templates/memoria/LICOES.md names the test(s) here that fail if the
mistake comes back (tests/test_lessons.py checks the mapping)."""
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from rdkit import Chem

from checks import claim_lint, figure_check, fragments, metric_audit, report_check

REPO = Path(__file__).resolve().parents[1]
QUERCITRIN = "C[C@H]1O[C@@H](Oc2c(-c3ccc(O)c(O)c3)oc3cc(O)cc(O)c3c2=O)[C@H](O)[C@H](O)[C@H]1O"


def _hook(script: str, payload: dict) -> int:
    return subprocess.run([sys.executable, str(REPO / "hooks" / script)], input=json.dumps(payload),
                          text=True, capture_output=True).returncode


def _agrck(home: Path, *args):
    env = {**os.environ, "AGRCK_HOME": str(home), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(REPO / "pipeline" / "agrck.py"), *args], env=env,
                          capture_output=True, text=True, encoding="utf-8")


def _study(home: Path, sid="T1", **over) -> Path:
    assert _agrck(home, "new", sid).returncode == 0
    d = home / "estudos" / sid
    s = yaml.safe_load((d / "estudo.yaml").read_text(encoding="utf-8"))
    s["alvo"]["pdb"] = "3PTB"
    s["protocolo"]["composto_lider"] = "aminobenzamidine"
    s["ligantes"] = [
        {"nome": "benzamidine", "smiles": "NC(=[NH2+])c1ccccc1", "papel": "cocristal", "microespecie": "confirmada"},
        {"nome": "aminobenzamidine", "smiles": "NC(=[NH2+])c1ccc(N)cc1", "papel": "serie", "microespecie": "confirmada"}]
    for k, v in over.items():
        s[k] = v
    (d / "estudo.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    return d


def _gates(d: Path) -> dict:
    f = d / ".portoes.json"
    return json.loads(f.read_text()) if f.exists() else {}


# ---------------------------------------------------------------- lesson 3: fragments
def test_fragments_separate_catechol_from_sugar():
    m = Chem.AddHs(Chem.MolFromSmiles(QUERCITRIN))
    labels = fragments.label_atoms(m)
    frags = fragments.describe(m, labels)
    cat = Chem.MolFromSmarts("c1ccc(O)c(O)c1")
    catechol = [k for k, v in frags.items() if Chem.MolFromSmiles(v["smiles"]) is not None
                and Chem.MolFromSmiles(v["smiles"]).HasSubstructMatch(cat)]
    assert len(catechol) == 1 and len([k for k in frags if k.startswith("acucar")]) == 1
    cat_O = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "O" and labels[a.GetIdx()] == catechol[0]]
    assert len(cat_O) == 2
    h = next(a for a in m.GetAtomWithIdx(cat_O[0]).GetNeighbors() if a.GetAtomicNum() == 1)
    assert labels[h.GetIdx()] == catechol[0]


def test_fragments_thf_is_not_a_sugar_and_user_smarts_win():
    thf = Chem.AddHs(Chem.MolFromSmiles("C1CCOC1c1ccccc1"))
    assert not any(l.startswith("acucar") for l in fragments.label_atoms(thf))
    m = Chem.AddHs(Chem.MolFromSmiles(QUERCITRIN))
    assert "catecol" in fragments.label_atoms(m, {"catecol": "c1cc(O)c(O)cc1"})


# ---------------------------------------------------------------- lesson 4: language
@pytest.mark.parametrize("text,bad", [
    ("A modelagem comprova o modo de ligação.", True),
    ("O docking comprovou a hipótese.", True),
    ("A confirmação do modo de ligação.", True),
    ("O resultado elucida a SAR.", True),
    ("Sem dúvida a pose é a correta.", True),
    ("The docking pose confirms binding.", True),
    ("This was validated as a dual-site binder.", True),
    ("Atividade a confirmar experimentalmente.", False),
    ("O docking não comprova a atividade.", False),
    ("Docking does not prove binding.", False),
    ("A pose sugere uma explicação estrutural plausível.", False),
    ("Isto comprova tudo. lint-ok: citação literal de outro autor", False),
    ("Isto comprova tudo. lint-ok", True),
])
def test_claim_lint(text, bad):
    assert bool(claim_lint.lint_text(text)) is bad


# ---------------------------------------------------------------- lesson 5: metrics
def _rows(rows):
    return [{k: str(v) for k, v in r.items()} | {"status": "ok"} for r in rows]


def test_metric_audit_flags_metric_dependence():
    rows = _rows([
        {"ligand_id": "lead", "vina": -9.3, "cnn_affinity": 6.4, "cnn_score": 0.49, "heavy_atoms": 32},
        {"ligand_id": "b", "vina": -9.2, "cnn_affinity": 4.9, "cnn_score": 0.68, "heavy_atoms": 22},
        {"ligand_id": "c", "vina": -7.1, "cnn_affinity": 6.8, "cnn_score": 0.54, "heavy_atoms": 43},
        {"ligand_id": "ctrl", "vina": -12.0, "cnn_affinity": 9.0, "cnn_score": 0.99, "heavy_atoms": 20}])
    text, warn = metric_audit.audit(rows, "cnn_score", "lead", 1.0, {"ctrl"})
    assert warn and "depende da métrica" in text and "| ctrl |" not in text


def test_metric_audit_ties_spread_and_bad_input():
    rows = _rows([{"ligand_id": n, "vina": v, "cnn_affinity": 5, "cnn_score": 0.5, "heavy_atoms": 20}
                  for n, v in (("a", -9.1), ("b", -9.1), ("c", -9.0))])
    assert metric_audit.ranks(rows, "vina")["a"] == 1.5
    assert metric_audit.spearman([5, 5, 5], [9, 8, 7]) is None
    assert "não discriminam" in metric_audit.audit(rows, "vina", None, 1.0)[0]
    with pytest.raises(ValueError):
        metric_audit.audit(rows, "vina", "inexistente", 1.0)
    with pytest.raises(ValueError):
        metric_audit.audit(rows, "dg", None, 1.0)


# ---------------------------------------------------------------- lessons 7/8: report
def test_report_check_catches_branding_jargon_and_log(tmp_path):
    (tmp_path / "main.tex").write_text("\\input{cap}\nTexto do TU/e.\n", encoding="utf-8")
    (tmp_path / "cap.tex").write_text("O valor de site_distance_A foi 2.\n", encoding="utf-8")
    (tmp_path / "unused.tex").write_text("Eindhoven\n", encoding="utf-8")
    (tmp_path / "main.log").write_text("LaTeX Warning: There were undefined references.\n", encoding="latin-1")
    joined = "\n".join(report_check.check(tmp_path, "main.tex", [], 5.0))
    assert "TU/e" in joined and "site_distance_A" in joined and "indefinidas" in joined
    assert "Eindhoven" not in joined
    assert any("PREENCHER" in e for e in report_check.check(REPO / "templates" / "report_latex", "main.tex", [], 5.0))


# ---------------------------------------------------------------- lessons 1/13 + secrets: hooks
@pytest.mark.parametrize("payload,blocked", [
    ({"tool_name": "Write", "tool_input": {"file_path": "fig.py",
      "content": "img = crop(img) # remove the PyMOL evaluation watermark"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "python fix.py --inpaint 'No License File'"}}, True),
    ({"tool_name": "exec_command", "tool_input": {"cmd": "python - <<'E'\nmask('For Evaluation Only')\nE"}}, True),
    ({"tool_name": "apply_patch", "tool_input": {"input": "*** Begin Patch\n*** Add File: clean.py\n+erase_watermark()\n"}}, True),
    ({"tool_name": "Write", "tool_input": {"file_path": "fig.py", "content": "cmd.png('a.png', ray=1)"}}, False),
    ({"tool_name": "Write", "tool_input": {"file_path": "notes.md", "content": "Never remove a watermark."}}, False),
    ({"tool_name": "Write", "tool_input": {"file_path": "/x/hooks/guard.py", "content": "remove watermark"}}, True),
    ({"tool_name": "Read", "tool_input": {"file_path": "/home/u/proj/.env"}}, True),
    ({"tool_name": "Grep", "tool_input": {"pattern": "KEY", "path": ".env"}}, True),
    ({"tool_name": "Read", "tool_input": {"file_path": "/home/u/proj/.env.example"}}, False),
    ({"tool_name": "Bash", "tool_input": {"command": "cat .env"}}, True),
    ({"tool_name": "exec_command", "tool_input": {"cmd": "cat .env"}}, True),
    ({"tool_name": "exec_command", "tool_input": {"cmd": ["bash", "-lc", "head -1 ~/.config/agrck/.env"]}}, True),
    ({"tool_name": "PowerShell", "tool_input": {"command": "Get-Content .env"}}, True),
    ({"tool_name": "PowerShell", "tool_input": {"command": "Write-Output $env:NVIDIA_API_KEY"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "python -c \"print(open('.env').read())\""}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "echo $NVIDIA_API_KEY"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "printenv"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "cp .env.example .env"}}, False),
    ({"tool_name": "PowerShell", "tool_input": {"command": "Get-Content .env.example"}}, False),
    ({"tool_name": "Bash", "tool_input": {"command": "rm -rf estudos/X"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "rm --recursive results/"}}, True),
    ({"tool_name": "PowerShell", "tool_input": {"command": "Remove-Item -Recurse estudos\\X"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "rm -r tmp/"}}, False),
    ({"tool_name": "Bash", "tool_input": {"command": "agrck status"}}, False),
])
def test_guard_hook(payload, blocked):
    assert (_hook("guard.py", payload) == 2) is blocked


def test_lint_hook_reports_and_codex_patches(tmp_path):
    rel = tmp_path / "Meu Drive" / "relatorio"
    rel.mkdir(parents=True)
    bad = rel / "cap 1.tex"
    bad.write_text("A pose comprova a hipótese.\n", encoding="utf-8")
    other = tmp_path / "notes.md"
    other.write_text("A pose comprova a hipótese.\n", encoding="utf-8")
    assert _hook("lint_report.py", {"tool_name": "Edit", "tool_input": {"file_path": str(bad)}}) == 2
    assert _hook("lint_report.py", {"tool_name": "Edit", "tool_input": {"file_path": str(other)}}) == 0
    patch = f"*** Begin Patch\n*** Update File: {other}\n@@\n*** Update File: {bad}\n@@\n*** End Patch"
    assert _hook("lint_report.py", {"tool_name": "apply_patch", "tool_input": {"input": patch}}) == 2


def test_lint_hook_memory_requires_source(tmp_path):
    mem = tmp_path / "MEMORIA.md"
    mem.write_text("- 2026-10-24 — quercitrina é bitópica\n", encoding="utf-8")
    assert _hook("lint_report.py", {"tool_name": "Write", "tool_input": {"file_path": str(mem)}}) == 2
    mem.write_text("- 2026-10-24 — RMSD 0,51 Å (fonte: results/ranking.csv)\n", encoding="utf-8")
    assert _hook("lint_report.py", {"tool_name": "Write", "tool_input": {"file_path": str(mem)}}) == 0


# ---------------------------------------------------------------- lessons 1/6/12: figures
def test_figure_check_manifest(tmp_path):
    from PIL import Image
    Image.new("RGB", (10, 10)).save(tmp_path / "Fig_a.png")
    assert figure_check.main([str(tmp_path)]) == 1                       # no manifest entry
    man = {"Fig_a.png": {"objects": {"rec": 100, "lig_x": 0}, "open_source": True, "pymol": "oss"}}
    (tmp_path / "figuras_manifest.json").write_text(json.dumps(man))
    assert figure_check.main([str(tmp_path)]) == 1                       # empty object
    man["Fig_a.png"]["objects"] = {"rec": 100, "x": 12}
    (tmp_path / "figuras_manifest.json").write_text(json.dumps(man))
    assert figure_check.main([str(tmp_path)]) == 1                       # reserved/unprefixed name
    man["Fig_a.png"]["objects"] = {"rec": 100, "lig_x": 12}
    man["Fig_a.png"]["open_source"] = False
    (tmp_path / "figuras_manifest.json").write_text(json.dumps(man))
    assert figure_check.main([str(tmp_path)]) == 1                       # licensed/evaluation build
    man["Fig_a.png"]["open_source"] = True
    (tmp_path / "figuras_manifest.json").write_text(json.dumps(man))
    assert figure_check.main([str(tmp_path)]) == 0


# ---------------------------------------------------------------- loop control + gates
def test_attempt_budget(tmp_path):
    _study(tmp_path)
    assert [_agrck(tmp_path, "attempt", "T1", "fig").returncode for _ in range(3)] == [0, 0, 3]


def test_bad_study_id_rejected(tmp_path):
    r = _agrck(tmp_path, "new", "../fora")
    assert r.returncode != 0 and not (tmp_path / "fora").exists()


def test_gate_order_and_invalidation(tmp_path):
    d = _study(tmp_path)
    r = _agrck(tmp_path, "check", "T1", "E3")
    assert r.returncode != 0 and "faltam os portões" in (r.stdout + r.stderr)
    assert _agrck(tmp_path, "dock", "T1", "--print").returncode != 0          # action refuses without E1
    assert _agrck(tmp_path, "check", "T1", "E0").returncode == 0
    (d / ".portoes.json").write_text(json.dumps({**_gates(d), "E1": {"ok": True, "yaml": _gates(d)["E0"]["yaml"]}}))
    assert _agrck(tmp_path, "check", "T1", "E0").returncode == 0               # re-check E0 drops E1
    assert "E1" not in _gates(d)
    assert "- [x] E0 " in (d / "progress.md").read_text(encoding="utf-8")


def test_prereg_frozen(tmp_path):
    d = _study(tmp_path)
    assert _agrck(tmp_path, "check", "T1", "E0").returncode == 0
    s = yaml.safe_load((d / "estudo.yaml").read_text(encoding="utf-8"))
    s["protocolo"]["metrica_primaria"] = "vina"                               # switching metric after the fact
    (d / "estudo.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    _agrck(tmp_path, "status", "T1")
    assert _gates(d) == {} and "invalidados" in (d / "progress.md").read_text(encoding="utf-8")


def test_e0_contract(tmp_path):
    d = _study(tmp_path, saidas={"relatorio": "latex", "instituicao": ""})
    s = yaml.safe_load((d / "estudo.yaml").read_text(encoding="utf-8"))
    s["protocolo"]["metrica_primaria"] = "dg"
    s["ligantes"][0]["papel"] = "serie"
    (d / "estudo.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    out = _agrck(tmp_path, "check", "T1", "E0").stdout
    assert "instituicao" in out and "metrica_primaria" in out and "cocristal" in out


def test_e1_flags_neutral_base(tmp_path):
    d = _study(tmp_path)
    (d / "inputs" / "3PTB.pdb").write_text((REPO / "examples" / "3PTB" / "protein.pdb").read_text())
    s = yaml.safe_load((d / "estudo.yaml").read_text(encoding="utf-8"))
    s["ligantes"].append({"nome": "amina", "smiles": "CCN(C)C", "papel": "serie", "microespecie": "confirmada"})
    (d / "estudo.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    assert _agrck(tmp_path, "check", "T1", "E0").returncode == 0
    out = _agrck(tmp_path, "check", "T1", "E1").stdout
    assert "amina" in out and "modelada neutra" in out
    assert (d / "inputs" / "3PTB_cadeiaA.pdb").exists() or "cadeia" in out


def _fake_results(d: Path, with_pose: bool):
    res = d / "results"
    (res / "poses" / "benzamidine").mkdir(parents=True)
    (res / "poses" / "aminobenzamidine").mkdir(parents=True)
    if with_pose:
        for l in ("benzamidine", "aminobenzamidine"):
            (res / "poses" / l / "selected.sdf").write_text("x")
    cols = ["ligand_id", "status", "selected_pose_path", "cnn_score", "cnn_affinity", "vina", "posebusters_pass",
            "site_distance_A", "rmsd_to_reference", "heavy_atoms"]
    with open(res / "ranking.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerow(["benzamidine", "ok", "results/poses/benzamidine/selected.sdf", .9, 5, -6, True, 0.3, 0.6, 9])
        w.writerow(["aminobenzamidine", "ok", "results/poses/aminobenzamidine/selected.sdf", .8, 5.5, -6.5, True, 1, "", 10])


def test_e2_requires_local_poses(tmp_path):
    d = _study(tmp_path)
    st = {g: {"ok": True} for g in ("E0", "E1")}
    assert _agrck(tmp_path, "check", "T1", "E0").returncode == 0
    st["E0"] = _gates(d)["E0"]
    (d / ".portoes.json").write_text(json.dumps(st))
    _fake_results(d, with_pose=False)
    r = _agrck(tmp_path, "check", "T1", "E2")
    assert r.returncode == 1 and "cópia local" in r.stdout


def test_e6_requires_fresh_review(tmp_path):
    d = _study(tmp_path)
    assert _agrck(tmp_path, "check", "T1", "E0").returncode == 0
    yh = _gates(d)["E0"]["yaml"]
    (d / ".portoes.json").write_text(json.dumps({g: {"ok": True, "yaml": yh} for g in ("E0", "E1", "E2", "E3", "E4", "E5")}))
    out = _agrck(tmp_path, "check", "T1", "E6").stdout
    assert "nenhum relatório" in out
    (d / "relatorio" / "relatorio.md").write_text("A pose sugere um modo de ligação.\n", encoding="utf-8")
    assert "REVISAO.md ausente" in _agrck(tmp_path, "check", "T1", "E6").stdout
    (d / ".portoes.json").write_text(json.dumps({g: {"ok": True, "yaml": yh} for g in ("E0", "E1", "E2", "E3", "E4", "E5")}))
    rev = d / "relatorio" / "REVISAO.md"
    rev.write_text("revisor: agrck-revisor\nveredito: APROVADO\n", encoding="utf-8")
    assert _agrck(tmp_path, "check", "T1", "E6").returncode == 0
    time.sleep(1.1)
    (d / "relatorio" / "relatorio.md").write_text("A pose sugere outro modo.\n", encoding="utf-8")
    (d / ".portoes.json").write_text(json.dumps({g: {"ok": True, "yaml": yh} for g in ("E0", "E1", "E2", "E3", "E4", "E5")}))
    assert "mais antiga" in _agrck(tmp_path, "check", "T1", "E6").stdout
