"""End-to-end run.py with a SIMULATED DiffDock API (real RDKit, PoseBusters, GNINA)."""
import csv
import json

import pytest
from rdkit import Chem

import diffdock_client
import run
from conftest import mock_response, needs_gnina, placed_on_reference, reference


def fake_post(self, payload):
    name = Chem.MolFromMolBlock(payload["ligand"], removeHs=False).GetProp("_Name")
    m = reference() if name == "benzamidine" else placed_on_reference("NC(=[NH2+])c1ccc(N)cc1")
    fake_post.calls += 1
    return mock_response(m, payload["num_poses"])


@needs_gnina
def test_full_pipeline_and_resume(workdir, monkeypatch):
    fake_post.calls = 0
    monkeypatch.setattr(diffdock_client.DiffDockClient, "_post", fake_post)
    monkeypatch.setenv("NVIDIA_API_KEY", "simulated")
    out = workdir / "results"
    args = ["--protein", str(workdir / "protein.pdb"), "--ligands", str(workdir / "ligands.sdf"),
            "--poses", "5", "--reference-ligand", str(workdir / "reference_ligand.sdf"), "--out", str(out)]
    assert run.main(args) == 0
    assert fake_post.calls == 2

    rows = list(csv.DictReader(open(out / "ranking.csv")))
    assert {r["ligand_id"] for r in rows} == {"benzamidine", "4_aminobenzamidine"}
    assert [r["rank"] for r in rows] == ["1.0", "2.0"]
    for r in rows:
        assert r["status"] == "ok" and r["posebusters_pass"] == "True"
        assert r["selected_pose"] in ("1", "2")
        # CSV values equal the properties written into the selected SDF and gnina output
        sel = next(iter(Chem.SDMolSupplier(r["selected_pose_path"], removeHs=False)))
        assert float(sel.GetProp("cnn_affinity")) == pytest.approx(float(r["cnn_affinity"]), abs=1e-3)
        gn = {m.GetProp("_Name"): m for m in Chem.SDMolSupplier(str(out / "poses" / r["ligand_id"] / "gnina_scored.sdf"))}
        g = gn[f"{r['ligand_id']}_pose{int(r['selected_pose']):02d}"]
        assert float(g.GetProp("CNNscore")) == pytest.approx(float(r["cnn_score"]), abs=1e-3)
        assert float(g.GetProp("minimizedAffinity")) == pytest.approx(float(r["vina"]), abs=1e-3)
    bz = next(r for r in rows if r["ligand_id"] == "benzamidine")
    assert float(bz["rmsd_to_reference"]) < 0.01          # crystal pose recovered (simulated input)

    poses = list(csv.DictReader(open(out / "poses.csv")))
    assert len(poses) == 10 and sum(p["selected"] == "True" for p in poses) == 2

    meta = json.loads((out / "metadata.json").read_text())
    assert meta["versions"]["gnina"].startswith("gnina v1.3")
    assert meta["parameters"]["num_poses"] == 5 and not meta["failures"]
    assert meta["inputs"]["protein_sha256"] and meta["selected_pose_sha256"]["benzamidine"]

    # 2D interaction analysis (PDB2PQR/PROPKA + ProLIF)
    inter = meta["interactions"]
    assert "error" not in inter, inter
    assert not any(k.startswith("CYS") for k in inter["protein_charged_atoms"])   # disulfides perceived
    ints = list(csv.DictReader(open(out / "interactions" / "interactions.csv")))
    bz_int = {(i["residue"], i["interaction"]) for i in ints if i["ligand_id"] == "benzamidine"}
    assert ("ASP189.A", "Cationic") in bz_int and ("ASP189.A", "HBDonor") in bz_int   # S1 salt bridge
    hb = next(i for i in ints if i["interaction"] == "HBDonor")
    assert float(hb["distance_A"]) < 3.5 and float(hb["DHA_angle_deg"]) > 120
    for f in ("benzamidine_2d.png", "benzamidine_lignetwork.html"):
        assert (out / "interactions" / f).stat().st_size > 0

    # resume: nothing re-requested, identical ranking
    assert run.main(args) == 0
    assert fake_post.calls == 2
    assert list(csv.DictReader(open(out / "ranking.csv"))) == rows


@needs_gnina
def test_failed_ligand_is_recorded_and_others_continue(workdir, monkeypatch):
    def flaky(self, payload):
        if "4_aminobenzamidine" in payload["ligand"]:
            raise diffdock_client.DiffDockError("HTTP 500: simulated outage")
        return fake_post(self, payload)
    fake_post.calls = 0
    monkeypatch.setattr(diffdock_client.DiffDockClient, "_post", flaky)
    monkeypatch.setenv("NVIDIA_API_KEY", "simulated")
    out = workdir / "results"
    assert run.main(["--protein", str(workdir / "protein.pdb"), "--ligands", str(workdir / "ligands.sdf"),
                     "--poses", "3", "--out", str(out)]) == 0
    rows = {r["ligand_id"]: r for r in csv.DictReader(open(out / "ranking.csv"))}
    assert rows["benzamidine"]["status"] == "ok" and rows["4_aminobenzamidine"]["status"] == "failed"
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["failures"][0]["ligand_id"] == "4_aminobenzamidine"
    # no --reference-ligand: the co-crystal BEN of the PDB is used automatically (redocking)
    assert rows["benzamidine"]["reference"] == "BEN A 1"
    assert float(rows["benzamidine"]["rmsd_to_reference"]) < 0.01
    assert meta["redocking"]["candidates"] == [{"label": "BEN A 1", "heavy_atoms": 9, "matched_ligand": "benzamidine"}]


@needs_gnina
def test_minimize_option(workdir, monkeypatch):
    fake_post.calls = 0
    monkeypatch.setattr(diffdock_client.DiffDockClient, "_post", fake_post)
    monkeypatch.setenv("NVIDIA_API_KEY", "simulated")
    out = workdir / "results"
    assert run.main(["--protein", str(workdir / "protein.pdb"), "--ligands", str(workdir / "ligands.sdf"),
                     "--poses", "3", "--minimize", "--out", str(out)]) == 0
    rows = {r["ligand_id"]: r for r in csv.DictReader(open(out / "ranking.csv"))}
    bz = rows["benzamidine"]
    assert bz["all_poses_path"].endswith("all_poses_min.sdf") and bz["posebusters_pass"] == "True"
    assert float(bz["rmsd_to_reference"]) < 1.0           # crystal pose stays in place after local minimisation
    poses = [p for p in csv.DictReader(open(out / "poses.csv")) if p["ligand_id"] == "benzamidine"]
    assert all(p["min_shift_A"] and p["pose_path"].endswith("_min.sdf") for p in poses)
    assert float(poses[0]["rmsd_to_reference_diffdock"]) < 0.01
    # minimised SDF keeps the prepared ligand chemistry (charge, bond orders) and the CSV scores
    sel = next(iter(Chem.SDMolSupplier(bz["selected_pose_path"], removeHs=False)))
    assert Chem.GetFormalCharge(sel) == 1 and Chem.MolToSmiles(Chem.RemoveHs(sel)) == bz["smiles"]
    meta = json.loads((out / "metadata.json").read_text())
    assert "--minimize" in meta["gnina_minimize_command_example"]
