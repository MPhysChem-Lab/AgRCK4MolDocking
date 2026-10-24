from rdkit import Chem

import preparation as prep
from conftest import INPUTS

CFG = {"embed_seed": 42, "keep_waters": False, "keep_metals": True, "keep_het": []}


def _xyz(lines):
    return {l[:27]: l[30:54] for l in lines if l.startswith(("ATOM", "HETATM"))}


def test_protein_report_and_coordinates_preserved(tmp_path):
    rep = prep.prepare_protein(INPUTS / "protein.pdb", tmp_path, CFG)
    kinds = {(g["resn"], g["kind"]) for g in rep["hetero_groups"]}
    assert ("CA", "metal") in kinds and ("BEN", "hetero") in kinds and ("HOH", "water") in kinds
    text = " ".join(rep["warnings"])
    assert "no hydrogens" in text and "BEN" in text and "Metal ions present: CA" in text
    src = _xyz((INPUTS / "protein.pdb").read_text().splitlines())
    for f in ("receptor_diffdock", "receptor_gnina"):
        out = _xyz(open(rep[f]).read().splitlines())
        assert out and all(src[k] == v for k, v in out.items())  # identical coordinates
    gn = open(rep["receptor_gnina"]).read()
    assert "CA A 480" in gn and "HOH" not in gn and "BEN" not in gn
    assert "HETATM" not in open(rep["receptor_diffdock"]).read()
    assert len(rep["metal_coords"]) == 1


def test_ligands_charge_recorded_not_changed(tmp_path):
    ligs = prep.prepare_ligands(INPUTS / "ligands.sdf", tmp_path, CFG)
    assert [l.id for l in ligs] == ["benzamidine", "4_aminobenzamidine"]
    for l in ligs:
        assert l.status == "ok" and l.info["formal_charge"] == 1
        assert "amidinium_guanidinium" in l.info["ionizable_groups"]
        assert any("AS PROVIDED" in w for w in l.warnings)
        assert Chem.MolFromMolFile(l.path, removeHs=False).GetNumAtoms() == l.mol.GetNumAtoms()


def test_smiles_input_gets_3d_and_bad_inputs_flagged(tmp_path):
    smi = tmp_path / "x.smi"
    smi.write_text("NC(=[NH2+])c1ccccc1 benz\nC[N](C)(C)(C)C bad_valence\nCC(O)CC.[Na+].[Cl-] salt\nCC(F)Cl chiral\n")
    ligs = {l.name: l for l in prep.prepare_ligands(smi, tmp_path / "o", CFG)}
    assert ligs["benz"].status == "ok" and not ligs["benz"].info["input_had_3d"]
    assert ligs["benz"].mol.GetConformer().Is3D()
    assert ligs["bad_valence"].status == "invalid" and "sanitization" in ligs["bad_valence"].error
    assert any("fragments" in w for w in ligs["salt"].warnings)
    assert any("unspecified stereo" in w for w in ligs["chiral"].warnings)


def test_unique_ids():
    used = set()
    assert [prep._unique_id(n, used) for n in ["a b", "a b", "a/b", "a-b"]] == ["a_b", "a_b_2", "a_b_3", "a_b_4"]


def test_metal_inside_cofactor_is_not_a_metal_ion(tmp_path):
    pdb = tmp_path / "p.pdb"
    src = (INPUTS / "protein.pdb").read_text().splitlines()
    het = ["HETATM 9001 FE   HEM A 900       1.000   1.000   1.000  1.00 10.00          FE  ",
           "HETATM 9002  NA  HEM A 900       2.000   1.000   1.000  1.00 10.00           N  "]
    pdb.write_text("\n".join([l for l in src if l.startswith("ATOM")] + het + ["END"]) + "\n")
    rep = prep.prepare_protein(pdb, tmp_path / "o", CFG)
    hem = next(g for g in rep["hetero_groups"] if g["resn"] == "HEM")
    assert hem["kind"] == "hetero" and not hem["kept_for_gnina"] and rep["metal_coords"] == []
    assert "HEM" not in open(rep["receptor_gnina"]).read()


def test_rmsd_returns_none_on_tautomer_mismatch():
    import rescoring as rs
    from rdkit.Chem import AllChem
    a = Chem.AddHs(Chem.MolFromSmiles("Oc1ccccn1")); AllChem.EmbedMolecule(a, randomSeed=1)
    b = Chem.AddHs(Chem.MolFromSmiles("O=c1cccc[nH]1")); AllChem.EmbedMolecule(b, randomSeed=1)
    assert rs.rmsd_to_reference(a, b) is None


def test_cocrystal_reference_extracted_from_pdb(tmp_path):
    import rescoring as rs
    from conftest import reference
    ligs = prep.prepare_ligands(INPUTS / "ligands.sdf", tmp_path, CFG)
    cands = prep.cocrystal_ligands(INPUTS / "protein.pdb", CFG)
    assert [c["label"] for c in cands] == ["BEN A 1"]          # waters and CA ion are not candidates
    prep.assign_reference_bond_orders(cands, ligs)
    assert cands[0]["matched_ligand"] == "benzamidine"         # not 4-aminobenzamidine
    assert rs.rmsd_to_reference(reference(), cands[0]["mol"]) < 1e-3
    amino = next(l for l in ligs if l.id == "4_aminobenzamidine")
    assert rs.rmsd_to_reference(amino.mol, cands[0]["mol"]) is None


def test_additives_and_small_groups_are_not_references(tmp_path):
    src = (INPUTS / "protein.pdb").read_text().splitlines()
    ben = [l for l in src if l.startswith("HETATM") and l[17:20] == "BEN"]
    gol = [l[:17] + "GOL" + l[20:] for l in ben[:6]]
    gol = [l[:22] + "   2" + l[26:] for l in gol]
    pdb = tmp_path / "p.pdb"
    pdb.write_text("\n".join([l for l in src if l.startswith("ATOM")] + gol + ["END"]) + "\n")
    assert prep.cocrystal_ligands(pdb, CFG) == []
    assert prep.cocrystal_ligands(INPUTS / "protein.pdb", {**CFG, "exclude_resn": ["BEN"]}) == []


def test_physicochemical_props_and_pains_and_neutral_amine_warning(tmp_path):
    smi = tmp_path / "medchem.smi"
    # trimethylamine (neutral basic aliphatic amine) + catechol/rhodanine-like PAINS test
    smi.write_text("CN(C)CCc1ccccc1 neutral_amine\nO=C1CSC(=S)N1Cc2ccccc2 rhodanine\n")
    ligs = {l.name: l for l in prep.prepare_ligands(smi, tmp_path / "o", CFG)}
    na = ligs["neutral_amine"]
    assert na.status == "ok" and "clogp" in na.info and "tpsa" in na.info
    assert any("dominant microspecies at assay pH" in w for w in na.warnings)
    rh = ligs["rhodanine"]
    assert rh.status == "ok" and isinstance(rh.info["pains_alerts"], list)
