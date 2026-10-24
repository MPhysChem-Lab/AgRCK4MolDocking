"""2D protein-ligand interaction diagrams for ranked ligands (ProLIF).

The receptor is protonated with PDB2PQR + PROPKA at the configured pH *for
this analysis only* (GNINA scoring uses its own receptor). Interactions are
detected by ProLIF with explicit-hydrogen geometric criteria (e.g. H-bond
distance and D-H...A angle); VdW contacts are not drawn.

Outputs per ligand in results/interactions/:
  <id>_lignetwork.html  interactive 2D diagram (ProLIF LigNetwork)
  <id>_2d.png           static 2D depiction, interacting atoms highlighted
  <id>.csv              one row per interaction (residue, type, distance, angle, ligand_fragment)
  <id>_fragments.json   fragment label -> ligand atoms + SMILES (check which ring is which)
plus interactions.csv (all ligands).

python interactions.py [--results results] [--ligand ID] [--top N]
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import warnings
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D

from checks import fragments as frag

ROOT = Path(__file__).resolve().parent
DEFAULT_TYPES = ["Hydrophobic", "HBDonor", "HBAcceptor", "Cationic", "Anionic", "PiStacking",
                 "CationPi", "PiCation", "XBDonor", "XBAcceptor"]
TYPE_COLORS = {"HBDonor": (0.2, 0.6, 1.0), "HBAcceptor": (0.2, 0.6, 1.0), "Cationic": (1.0, 0.4, 0.4),
               "Anionic": (1.0, 0.4, 0.4), "Hydrophobic": (0.4, 0.8, 0.3), "PiStacking": (0.8, 0.5, 1.0),
               "CationPi": (1.0, 0.7, 0.2), "PiCation": (1.0, 0.7, 0.2), "XBDonor": (0.3, 0.9, 0.9),
               "XBAcceptor": (0.3, 0.9, 0.9)}
CSV_COLUMNS = ["ligand_id", "rank", "residue", "interaction", "distance_A", "DHA_angle_deg", "ligand_atoms",
               "ligand_fragment"]


def protonate_receptor(receptor_pdb: str | Path, out_dir: str | Path, ph: float) -> tuple[Path, Path]:
    """PDB2PQR/PROPKA protonation; returns (protonated PDB, log). Coordinates of heavy atoms unchanged."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdb_h, pqr, log = out_dir / f"receptor_pH{ph:g}.pdb", out_dir / f"receptor_pH{ph:g}.pqr", out_dir / "pdb2pqr.log"
    exe = Path(sys.executable).parent / "pdb2pqr"
    cmd = [str(exe), "--ff=AMBER", "--titration-state-method=propka", f"--with-ph={ph}", "--keep-chain",
           "--pdb-output", str(pdb_h), str(receptor_pdb), str(pqr)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    log.write_text(" ".join(cmd) + "\n" + r.stdout + r.stderr)
    if r.returncode != 0 or not pdb_h.exists():
        raise RuntimeError(f"pdb2pqr failed (exit {r.returncode}); see {log}")
    return pdb_h, log


def load_protein(pdb_h: str | Path):
    """ProLIF protein with guessed bonds plus explicit disulfides (absent from PDB2PQR output)."""
    import MDAnalysis as mda
    import prolif as plf
    from MDAnalysis.lib.distances import self_capped_distance

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u = mda.Universe(str(pdb_h))
        u.atoms.guess_bonds()
        is_h = lambda a: a.element == "H" or a.name.startswith("H")
        hh_bonds = [tuple(sorted((b[0].index, b[1].index))) for b in u.bonds if is_h(b[0]) and is_h(b[1])]
        if hh_bonds:
            u.delete_bonds(hh_bonds)
        h_bonds: dict[int, list] = {}
        for b in u.bonds:
            for a in b:
                if is_h(a):
                    h_bonds.setdefault(a.index, []).append(b)
        drop = {tuple(sorted((b[0].index, b[1].index)))
                for h_idx, bs in h_bonds.items() if len(bs) > 1
                for b in sorted(bs, key=lambda x: (x[0].resid != x[1].resid, x.length()))[1:]}
        if drop:
            u.delete_bonds(list(drop))
        sg = u.select_atoms("resname CYS CYX and name SG")
        if len(sg) > 1:
            pairs, _ = self_capped_distance(sg.positions, 2.5)
            u.add_bonds([(sg[i].index, sg[j].index) for i, j in pairs])
        prot = plf.Molecule.from_mda(u)
    charged = {}
    for a in prot.GetAtoms():
        if a.GetFormalCharge():
            k = f"{a.GetPDBResidueInfo().GetResidueName()}{a.GetFormalCharge():+d}"
            charged[k] = charged.get(k, 0) + 1
    return prot, charged


def ligand_interactions(lig_sdf: str | Path, protein, types: list[str], frag_smarts: dict | None = None):
    import prolif as plf

    mol = next(iter(Chem.SDMolSupplier(str(lig_sdf), removeHs=False)))
    lig = plf.Molecule.from_rdkit(mol)
    fp = plf.Fingerprint(types)
    fp.run_from_iterable([lig], protein, progress=False)
    labels = frag.label_atoms(mol, frag_smarts)
    rows = []
    for (_, pres), ints in fp.ifp[0].items():
        for name, metas in ints.items():
            for m in metas:
                rows.append({"residue": str(pres), "interaction": name, "distance_A": round(m["distance"], 2),
                             "DHA_angle_deg": round(m["DHA_angle"], 1) if "DHA_angle" in m else None,
                             "ligand_atoms": list(m["parent_indices"]["ligand"]),
                             "ligand_fragment": frag.fragment_of(labels, m["parent_indices"]["ligand"])})
    return fp, lig, mol, rows, frag.describe(mol, labels)


def draw_2d(mol: Chem.Mol, rows: list[dict], path: str | Path, title: str) -> None:
    """Static 2D: heavy-atom ligand, interacting atoms coloured by type, residue labels as atom notes."""
    m = Chem.Mol(mol)
    heavy_of = {}
    for a in m.GetAtoms():
        heavy_of[a.GetIdx()] = a.GetIdx() if a.GetAtomicNum() > 1 else a.GetNeighbors()[0].GetIdx()
    notes: dict[int, list[str]] = {}
    colors = {}
    for r in rows:
        for i in r["ligand_atoms"]:
            h = heavy_of[i]
            label = f"{r['residue'].split('.')[0]} {r['interaction']}"
            if label not in notes.setdefault(h, []):
                notes[h].append(label)
            colors.setdefault(h, TYPE_COLORS.get(r["interaction"], (0.7, 0.7, 0.7)))
    for a in m.GetAtoms():
        a.SetIntProp("orig_idx", a.GetIdx())
    noh = Chem.RemoveHs(m)
    old2new = {a.GetIntProp("orig_idx"): a.GetIdx() for a in noh.GetAtoms()}
    for h, labels in notes.items():
        noh.GetAtomWithIdx(old2new[h]).SetProp("atomNote", "\n".join(labels))
    AllChem.Compute2DCoords(noh)
    d = rdMolDraw2D.MolDraw2DCairo(900, 700)
    opts = d.drawOptions()
    opts.annotationFontScale = 0.55
    opts.legendFontSize = 18
    hl = {old2new[h]: c for h, c in colors.items()}
    d.DrawMolecule(noh, highlightAtoms=list(hl), highlightAtomColors=hl, highlightBonds=[], legend=title)
    d.FinishDrawing()
    Path(path).write_bytes(d.GetDrawingText())


def run(ranked: list[dict], receptor_pdb: str | Path, out_dir: str | Path, cfg: dict) -> dict:
    from prolif.plotting.network import LigNetwork

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ph = float(cfg.get("ph", 7.4))
    pdb_h, log = protonate_receptor(receptor_pdb, out_dir, ph)
    protein, charged = load_protein(pdb_h)
    types = cfg.get("types", DEFAULT_TYPES)
    todo = [r for r in ranked if r.get("selected_pose_path")]
    top_n = int(cfg.get("top_n", 0) or 0)
    if top_n > 0:
        todo = todo[:top_n]
    all_rows, per_ligand = [], {}
    for r in todo:
        lid = r["ligand_id"]
        fp, lig, mol, rows, frags = ligand_interactions(r["selected_pose_path"], protein, types, cfg.get("fragments"))
        for x in rows:
            x.update(ligand_id=lid, rank=r.get("rank"))
        files = {"csv": str(out_dir / f"{lid}.csv"), "png": str(out_dir / f"{lid}_2d.png"),
                 "html": str(out_dir / f"{lid}_lignetwork.html"), "fragments": str(out_dir / f"{lid}_fragments.json")}
        _write_csv(files["csv"], rows)
        Path(files["fragments"]).write_text(json.dumps(frags, indent=1))
        title = f"#{_fmt_rank(r.get('rank'))} {lid} | CNNaffinity {float(r['cnn_affinity']):.2f} pK | " \
                f"Vina {float(r['vina']):.2f} kcal/mol"
        draw_2d(mol, rows, files["png"], title)
        if rows:
            LigNetwork.from_fingerprint(fp, lig, kind="frame", frame=0).save(files["html"])
        else:
            files["html"] = None
        per_ligand[lid] = {"n_interactions": len(rows), **files,
                           "residues": sorted({x["residue"] for x in rows})}
        all_rows += rows
    _write_csv(out_dir / "interactions.csv", all_rows)
    return {"receptor_protonated": str(pdb_h), "pdb2pqr_log": str(log), "ph": ph,
            "protein_charged_atoms": charged, "types": types, "ligands": per_ligand,
            "method": "PDB2PQR (AMBER, PROPKA) protonation + ProLIF fingerprint with explicit H; "
                      "VdW contacts not drawn; metal ions are not in the protonated receptor."}


def _fmt_rank(x) -> str:
    try:
        return f"{float(x):g}"
    except (TypeError, ValueError):
        return "?"


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for x in rows:
            w.writerow({**x, "ligand_atoms": " ".join(map(str, x["ligand_atoms"]))})


def main(argv=None) -> None:
    import yaml
    ap = argparse.ArgumentParser(description="ProLIF 2D interaction diagrams for ranked ligands")
    ap.add_argument("--results", default=str(ROOT / "results"))
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--ligand", help="only this ligand id")
    ap.add_argument("--top", type=int, help="number of top-ranked ligands (default: config; 0 = all)")
    ap.add_argument("--ph", type=float, help="receptor protonation pH (default: config)")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config)).get("interactions", {})
    if a.top is not None:
        cfg["top_n"] = a.top
    if a.ph is not None:
        cfg["ph"] = a.ph
    res = Path(a.results)
    ranked = [r for r in csv.DictReader(open(res / "ranking.csv")) if r.get("selected_pose_path")]
    if a.ligand:
        ranked = [r for r in ranked if r["ligand_id"] == a.ligand]
        cfg["top_n"] = 1
    meta = json.loads((res / "metadata.json").read_text())
    info = run(ranked, meta["protein"]["receptor_diffdock"], res / "interactions", cfg)
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
