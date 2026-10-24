"""Shared fixtures. DiffDock responses here are SIMULATED (built from the 3PTB
crystal pose plus rigid perturbations) - they test plumbing, not science."""
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
INPUTS = ROOT / "examples" / "3PTB"

GNINA = shutil.which("gnina")
needs_gnina = pytest.mark.skipif(GNINA is None, reason="gnina executable not on PATH")


def reference():
    return next(iter(Chem.SDMolSupplier(str(INPUTS / "reference_ligand.sdf"), removeHs=False)))


def _rotate(coords, deg, axis=(0, 0, 1)):
    t = np.radians(deg)
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    R = np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K
    c = coords.mean(0)
    return (coords - c) @ R.T + c


def diffdock_like_block(m: Chem.Mol, coords: np.ndarray) -> str:
    """Heavy atoms only, kekulized, charges stripped - mimics a bare DiffDock SDF."""
    h = Chem.RemoveHs(m)
    conf = h.GetConformer()
    for i, xyz in enumerate(coords):
        conf.SetAtomPosition(i, xyz.tolist())
    for a in h.GetAtoms():
        a.SetFormalCharge(0)
    h.UpdatePropertyCache(strict=False)
    return Chem.MolToMolBlock(h, kekulize=True)


def placed_on_reference(smiles: str) -> Chem.Mol:
    """Embed a benzamidine analogue and align its benzamidine core onto the crystal pose."""
    ref = Chem.RemoveHs(reference())
    m = Chem.AddHs(Chem.MolFromSmiles(smiles))
    p = AllChem.ETKDGv3()
    p.randomSeed = 1
    AllChem.EmbedMolecule(m, p)
    core = Chem.MolFromSmarts("NC(=N)c1ccccc1")
    amap = list(zip(m.GetSubstructMatch(core), ref.GetSubstructMatch(core)))
    rdMolAlign.AlignMol(m, ref, atomMap=amap)
    return m


def mock_response(m: Chem.Mol, n: int = 5) -> dict:
    """Pose 1 in the site, then rotated, displaced (8 A), buried (clash) and far away."""
    xyz = Chem.RemoveHs(m).GetConformer().GetPositions()
    variants = [xyz, _rotate(xyz, 35), xyz + [8, 0, 0], _rotate(xyz, 180, (1, 0, 0)) + [1.5, 1.5, 0], xyz + [25, 25, 25]]
    conf = [0.9, 0.2, -1.0, -2.0, -3.5]
    return {"status": "success", "details": "simulated",
            "ligand_positions": [diffdock_like_block(m, v) for v in variants[:n]],
            "position_confidence": conf[:n]}


@pytest.fixture
def workdir(tmp_path):
    for f in ("protein.pdb", "ligands.sdf", "reference_ligand.sdf", "ligands.smi"):
        shutil.copy(INPUTS / f, tmp_path / f)
    return tmp_path
