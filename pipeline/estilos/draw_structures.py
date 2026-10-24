"""2D structures of every ligand of a study (Introduction table), from the SMILES used in docking.

python draw_structures.py estudos/<ID>/estudo.yaml [--core SMARTS]
- same scale for every molecule (fixed bond length) and autocrop, so relative sizes are honest;
- optional --core: common scaffold drawn in the same orientation for every analogue;
- sugar rings highlighted (orange). Output: estudos/<ID>/figuras/estruturas/<nome>.png
"""
import argparse
import io
from pathlib import Path

import yaml
from PIL import Image, ImageChops
from rdkit import Chem
from rdkit.Chem import AllChem, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.MolStandardize import rdMolStandardize

SUGAR = Chem.MolFromSmarts("[C;X4;R]1~[C;X4;R]~[C;X4;R]~[C;X4;R]~[C;X4;R]~[O;X2;R]1")
ORANGE = (1.0, 0.82, 0.55)


def draw(mol, out: Path, core=None, core_ref=None) -> None:
    hl_a, hl_b, ca, cb = [], [], {}, {}
    if core is not None and mol.HasSubstructMatch(core):
        AllChem.GenerateDepictionMatching2DStructure(mol, core_ref, refPatt=core)
    else:
        rdDepictor.SetPreferCoordGen(True)
        rdDepictor.Compute2DCoords(mol)
    for match in mol.GetSubstructMatches(SUGAR):
        for a in match:
            hl_a.append(a); ca[a] = ORANGE
    for b in mol.GetBonds():
        if b.GetBeginAtomIdx() in ca and b.GetEndAtomIdx() in ca:
            hl_b.append(b.GetIdx()); cb[b.GetIdx()] = ORANGE
    d = rdMolDraw2D.MolDraw2DCairo(900, 700)
    o = d.drawOptions()
    o.bondLineWidth, o.fixedBondLength, o.addStereoAnnotation = 2, 30, False
    rdMolDraw2D.PrepareAndDrawMolecule(d, mol, highlightAtoms=hl_a, highlightBonds=hl_b,
                                       highlightAtomColors=ca, highlightBondColors=cb)
    d.FinishDrawing()
    im = Image.open(io.BytesIO(d.GetDrawingText())).convert("RGB")
    box = ImageChops.difference(im, Image.new("RGB", im.size, "white")).getbbox()
    im.crop((box[0] - 10, box[1] - 10, box[2] + 10, box[3] + 10)).save(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("estudo")
    ap.add_argument("--core", help="SMARTS of the common scaffold (element-only, e.g. [#6]1~[#6]~...)")
    ap.add_argument("--core-smiles", help="SMILES of the scaffold used as 2D template (same atom order as --core)")
    a = ap.parse_args()
    est = Path(a.estudo).resolve()
    s = yaml.safe_load(est.read_text(encoding="utf-8"))
    out = est.parent / "figuras" / "estruturas"
    out.mkdir(parents=True, exist_ok=True)
    core = Chem.MolFromSmarts(a.core) if a.core else None
    ref = None
    if a.core_smiles:
        ref = Chem.MolFromSmiles(a.core_smiles)
        rdDepictor.Compute2DCoords(ref)
    un = rdMolStandardize.Uncharger()
    for lig in s.get("ligantes", []):
        if not lig.get("smiles"):
            continue
        m = un.uncharge(Chem.MolFromSmiles(lig["smiles"]))  # neutral drawing; the docked microspecies is in the SMILES
        draw(m, out / f"{lig['nome']}.png", core if ref is not None else None, ref)
        print("ok", lig["nome"])


if __name__ == "__main__":
    main()
