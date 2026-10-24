"""Each test pins one lesson from templates/memoria/LICOES.md to a deterministic check."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from checks import claim_lint, fragments, metric_audit, report_check

REPO = Path(__file__).resolve().parents[1]
QUERCITRIN = "C[C@H]1O[C@@H](Oc2c(-c3ccc(O)c(O)c3)oc3cc(O)cc(O)c3c2=O)[C@H](O)[C@H](O)[C@H]1O"


def _hook(script: str, payload: dict) -> int:
    return subprocess.run([sys.executable, str(REPO / "hooks" / script)], input=json.dumps(payload),
                          text=True, capture_output=True).returncode


# lesson 3: interaction attributed to the wrong fragment
def test_fragments_separate_catechol_from_sugar():
    m = Chem.AddHs(Chem.MolFromSmiles(QUERCITRIN))
    labels = fragments.label_atoms(m)
    frags = fragments.describe(m, labels)
    catechol = [k for k, v in frags.items() if Chem.MolFromSmiles(v["smiles"]) is not None
                and Chem.MolFromSmiles(v["smiles"]).HasSubstructMatch(Chem.MolFromSmarts("c1ccc(O)c(O)c1"))]
    sugar = [k for k in frags if k.startswith("acucar")]
    assert len(catechol) == 1 and len(sugar) == 1
    cat_O = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "O" and labels[a.GetIdx()] == catechol[0]]
    assert len(cat_O) == 2                       # both catechol O belong to the B ring, not to the sugar
    h = next(a for a in m.GetAtomWithIdx(cat_O[0]).GetNeighbors() if a.GetAtomicNum() == 1)
    assert labels[h.GetIdx()] == catechol[0]     # H inherits its heavy atom's fragment


def test_fragments_user_smarts_take_precedence():
    m = Chem.AddHs(Chem.MolFromSmiles(QUERCITRIN))
    labels = fragments.label_atoms(m, {"catecol": "c1cc(O)c(O)cc1"})
    assert "catecol" in labels and not any(l.startswith("anel") and "catecol" in l for l in labels)


# lesson 4: over-claiming language
@pytest.mark.parametrize("text,bad", [
    ("A modelagem comprova o modo de ligação.", True),
    ("O resultado elucida a SAR.", True),
    ("The docking pose confirms binding.", True),
    ("Atividade a confirmar experimentalmente.", False),
    ("A pose sugere uma explicação estrutural plausível.", False),
    ("Isto comprova tudo. lint-ok citação literal de outro autor", False),
])
def test_claim_lint(text, bad):
    assert bool(claim_lint.lint_text(text)) is bad


# lesson 5: metric cherry-picking
def _ranking(tmp_path, rows):
    f = tmp_path / "ranking.csv"
    with open(f, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return list(csv.DictReader(open(f, encoding="utf-8")))


def test_metric_audit_flags_metric_dependence(tmp_path):
    rows = _ranking(tmp_path, [
        {"ligand_id": "lead", "vina": -9.3, "cnn_affinity": 6.4, "cnn_score": 0.49, "heavy_atoms": 32, "site_distance_A": 2.5},
        {"ligand_id": "b", "vina": -9.2, "cnn_affinity": 4.9, "cnn_score": 0.68, "heavy_atoms": 22, "site_distance_A": 9.8},
        {"ligand_id": "c", "vina": -7.1, "cnn_affinity": 6.8, "cnn_score": 0.54, "heavy_atoms": 43, "site_distance_A": 5.6},
    ])
    text, warn = metric_audit.audit(rows, "cnn_score", "lead", 1.0)
    assert warn and "depende da métrica" in text


def test_metric_audit_flags_small_spread(tmp_path):
    rows = _ranking(tmp_path, [{"ligand_id": n, "vina": v, "cnn_affinity": 5, "cnn_score": 0.5, "heavy_atoms": 20,
                                "site_distance_A": 3} for n, v in (("a", -9.1), ("b", -9.2), ("c", -9.0))])
    text, _ = metric_audit.audit(rows, "vina", None, 1.0)
    assert "não discriminam" in text


# lessons 7/8: template leftovers, jargon, compile log
def test_report_check_catches_branding_jargon_and_log(tmp_path):
    (tmp_path / "main.tex").write_text("\\input{cap}\nTexto do TU/e.\n", encoding="utf-8")
    (tmp_path / "cap.tex").write_text("O valor de site_distance_A foi 2.\n", encoding="utf-8")
    (tmp_path / "unused.tex").write_text("Eindhoven\n", encoding="utf-8")
    (tmp_path / "main.log").write_text("LaTeX Warning: There were undefined references.\n", encoding="latin-1")
    errs = report_check.check(tmp_path, "main.tex", [], 5.0)
    joined = "\n".join(errs)
    assert "TU/e" in joined and "site_distance_A" in joined and "indefinidas" in joined
    assert "Eindhoven" not in joined           # files not \input-ed are ignored


def test_report_template_has_placeholders_until_filled():
    errs = report_check.check(REPO / "templates" / "report_latex", "main.tex", [], 5.0)
    assert any("PREENCHER" in e for e in errs)


# lesson 1 and secrets: control hooks
@pytest.mark.parametrize("payload,blocked", [
    ({"tool_name": "Write", "tool_input": {"file_path": "fig.py",
      "content": "img = crop(img) # remove the PyMOL evaluation watermark"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "python fix.py --inpaint 'No License File'"}}, True),
    ({"tool_name": "Write", "tool_input": {"file_path": "fig.py", "content": "cmd.png('a.png', ray=1)"}}, False),
    ({"tool_name": "Write", "tool_input": {"file_path": "notes.md", "content": "Never remove a watermark."}}, False),
    ({"tool_name": "Read", "tool_input": {"file_path": "/home/u/proj/.env"}}, True),
    ({"tool_name": "Read", "tool_input": {"file_path": "/home/u/proj/.env.example"}}, False),
    ({"tool_name": "Bash", "tool_input": {"command": "cat .env"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "echo $NVIDIA_API_KEY"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "cp .env.example .env"}}, False),
    ({"tool_name": "Bash", "tool_input": {"command": "rm -rf estudos/X"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "agrck status"}}, False),
])
def test_guard_hook(payload, blocked):
    assert (_hook("guard.py", payload) == 2) is blocked


def test_lint_hook_only_on_reports(tmp_path):
    rel = tmp_path / "relatorio"
    rel.mkdir()
    bad = rel / "cap.tex"
    bad.write_text("A pose comprova a hipótese.\n", encoding="utf-8")
    other = tmp_path / "notes.md"
    other.write_text("A pose comprova a hipótese.\n", encoding="utf-8")
    assert _hook("lint_report.py", {"tool_name": "Edit", "tool_input": {"file_path": str(bad)}}) == 2
    assert _hook("lint_report.py", {"tool_name": "Edit", "tool_input": {"file_path": str(other)}}) == 0


# loop control + gates
def test_agrck_new_gate_and_attempt_budget(tmp_path, monkeypatch):
    env = {**__import__("os").environ, "AGRCK_HOME": str(tmp_path)}
    run = lambda *a: subprocess.run([sys.executable, str(REPO / "pipeline" / "agrck.py"), *a], env=env,
                                    capture_output=True, text=True)
    assert run("new", "T1").returncode == 0
    assert (tmp_path / "AGENTS.md").exists() and (tmp_path / "memoria" / "LICOES.md").exists()
    r = run("check", "T1", "E0")
    assert r.returncode == 1 and "alvo.pdb vazio" in r.stdout
    est = tmp_path / "estudos" / "T1" / "estudo.yaml"
    import yaml
    s = yaml.safe_load(est.read_text(encoding="utf-8"))
    s["alvo"]["pdb"] = "3PTB"
    s["protocolo"]["composto_lider"] = "benzamidine"
    s["ligantes"] = [{"nome": "benzamidine", "smiles": "NC(=[NH2+])c1ccccc1", "papel": "cocristal",
                      "microespecie": "confirmada"}]
    est.write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    r = run("check", "T1", "E0")
    assert r.returncode == 0, r.stdout
    assert "- [x] E0 " in (tmp_path / "estudos" / "T1" / "progress.md").read_text(encoding="utf-8")
    assert [run("attempt", "T1", "fig").returncode for _ in range(3)] == [0, 0, 3]
