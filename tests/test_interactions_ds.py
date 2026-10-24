import numpy as np
from rdkit import Chem

import interactions_ds as ds
from conftest import reference


def test_layout_separates_identical_anchors():
    anchors = np.array([[700.0, 500.0]] * 4)
    pos = ds._layout(anchors, np.array([[600.0, 500.0]]), np.array([600.0, 500.0]), top=70)
    d = np.linalg.norm(pos[:, None] - pos[None], axis=-1)[np.triu_indices(4, 1)]
    assert d.min() > 2 * ds.R          # no overlapping discs


def test_draw_ds_writes_png(tmp_path):
    m = reference()
    hb_h = next(a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum() == 1 and a.GetNeighbors()[0].GetAtomicNum() == 7)
    ring = [a.GetIdx() for a in m.GetAtoms() if a.GetIsAromatic()]
    rows = [{"residue": "ASP189.A", "interaction": "HBDonor", "ligand_atoms": [hb_h]},
            {"residue": "ASP189.A", "interaction": "Cationic", "ligand_atoms": [hb_h]},
            {"residue": "CYS220.A", "interaction": "Hydrophobic", "ligand_atoms": ring}]
    vdw = [{"residue": "SER190.A", "interaction": "VdWContact", "ligand_atoms": [0]}]
    out = tmp_path / "ds.png"
    ds.draw_ds(Chem.Mol(m), rows, out, "test", vdw)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and out.stat().st_size > 20000
    assert ds._residue_label("ASP189.A") == "ASP\nA:189"
