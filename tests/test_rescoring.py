import pytest
from rdkit import Chem

import preparation as prep
import rescoring as rs
from conftest import INPUTS, mock_response, needs_gnina, placed_on_reference, reference

GN_CFG = {"executable": "gnina", "use_gpu": False, "cpu": 2, "seed": 42}


def test_restore_pose_keeps_coordinates_and_charge():
    ref = reference()
    block = mock_response(ref, 1)["ligand_positions"][0]
    m = rs.restore_pose(block, ref)
    assert Chem.GetFormalCharge(m) == 1 and m.GetNumAtoms() == ref.GetNumAtoms()
    assert rs.rmsd_to_reference(m, ref) == pytest.approx(0.0, abs=1e-4)


def test_restore_pose_rejects_wrong_molecule():
    other = placed_on_reference("NC(=[NH2+])c1ccc(N)cc1")
    block = mock_response(other, 1)["ligand_positions"][0]
    with pytest.raises(rs.PoseError):
        rs.restore_pose(block, reference())


def test_select_pose_prefers_posebusters_valid():
    sc = {"cnn_affinity": 5.0, "vina": -6.0}
    poses = [{"diffdock_rank": 1, "cnn_score": 0.9, "pb_pass": False, **sc},
             {"diffdock_rank": 2, "cnn_score": 0.7, "pb_pass": True, **sc},
             {"diffdock_rank": 3, "cnn_score": 0.7, "pb_pass": True, **sc}]
    best, warns = rs.select_pose(poses)
    assert best["diffdock_rank"] == 2 and not warns
    best, warns = rs.select_pose([dict(p, pb_pass=False) for p in poses])
    assert best["diffdock_rank"] == 1 and warns
    assert rs.select_pose([{"diffdock_rank": 1}])[0] is None
    assert rs.select_pose([{"diffdock_rank": 1, "cnn_score": 0.9, "cnn_affinity": float("nan"), "vina": -5.0}])[0] is None
    # blind-docking guard: reject out-of-site surface pose when an in-site PB-valid pose exists
    site_poses = [
        {"diffdock_rank": 1, "cnn_score": 0.92, "pb_pass": True, "site_distance_A": 22.5, **sc},
        {"diffdock_rank": 2, "cnn_score": 0.81, "pb_pass": True, "site_distance_A": 2.4, **sc},
    ]
    best, warns = rs.select_pose(site_poses, require_pb=True, max_site_distance_A=12.0)
    assert best["diffdock_rank"] == 2 and any("outside active site" in w for w in warns)


def test_rank_by_cnnaffinity_and_report_vina_separately():
    rows = [{"ligand_id": i, "cnn_affinity": a, "vina": v, "heavy_atoms": h, "formal_charge": 0,
             "warnings": [], "status": "ok"}
            for i, a, v, h in [("a", 5.0, -6.0, 20), ("b", 7.0, -5.0, 22), ("c", 6.0, -9.0, 60), ("d", 4.0, -4.0, 21)]]
    rows.append({"ligand_id": "x", "cnn_affinity": None, "warnings": [], "status": "failed"})
    ranked, stats = rs.rank_ligands(rows, {})
    assert [r["ligand_id"] for r in ranked] == ["b", "c", "a", "d", "x"]
    assert [r["vina_rank"] for r in ranked[:4]] == [3, 1, 2, 4]
    assert ranked[0]["le_vina"] == pytest.approx(5.0 / 22, abs=1e-3)
    assert any("size-biased" in w for w in ranked[1]["warnings"])
    assert any("disagree" in w for w in ranked[0]["warnings"])
    assert stats["n_unranked"] == 1 and stats["spearman_cnnaffinity_vs_vina"] == pytest.approx(0.4)


def test_spearman_needs_three():
    assert rs.spearman([1, 2], [1, 2]) is None
    assert rs.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


@needs_gnina
def test_gnina_scores_and_posebusters_on_simulated_poses(tmp_path):
    rep = prep.prepare_protein(INPUTS / "protein.pdb", tmp_path, {"keep_metals": True})
    ref = reference()
    mols = []
    for k, b in enumerate(mock_response(ref)["ligand_positions"], 1):
        m = rs.restore_pose(b, ref)
        m.SetProp("_Name", f"p{k}")
        mols.append(m)
    sdf = tmp_path / "poses.sdf"
    rs.write_sdf(mols, sdf)
    scores, cmd = rs.run_gnina(rep["receptor_gnina"], sdf, tmp_path / "out.sdf", GN_CFG)
    assert "--score_only" in cmd and "--no_gpu" in cmd
    assert list(scores) == ["p1", "p2", "p3", "p4", "p5"]
    s1 = scores["p1"]
    assert {"vina", "cnn_score", "cnn_affinity"} <= set(s1)
    # crystal pose: plausible and favourable; the pose 25 A away has no contacts (Vina ~ 0).
    # NB: GNINA's CNNscore is NOT low for that detached pose (observed ~0.64), which is
    # why pose selection is gated by PoseBusters rather than CNNscore alone.
    assert s1["cnn_score"] > 0.5 and s1["vina"] < -4
    assert scores["p5"]["vina"] > -1
    pb = rs.posebusters_check(sdf, rep["receptor_gnina"])
    assert pb[0]["pb_pass"]
    assert not pb[3]["pb_pass"]                                # buried pose clashes
    assert "protein-ligand_maximum_distance" in pb[4]["pb_failed"]  # detached pose
    # values written in gnina's SDF match the parsed dict
    out = {m.GetProp("_Name"): m for m in rs.read_sdf(tmp_path / "out.sdf")}
    assert float(out["p1"].GetProp("CNNaffinity")) == pytest.approx(s1["cnn_affinity"])


def test_redocking_warnings():
    import run
    poses = [{"rmsd_to_reference": 0.5}, {"rmsd_to_reference": 3.0}]
    assert run.redocking_warnings(poses[0], poses, {}) == []
    assert "selection" in run.redocking_warnings(poses[1], poses, {})[0]
    far = [{"rmsd_to_reference": 4.0}, {"rmsd_to_reference": 6.0}]
    assert "FAILED" in run.redocking_warnings(far[0], far, {"rmsd_success_A": 2.0})[0]
    assert run.redocking_warnings({"rmsd_to_reference": None}, [], {}) == []
