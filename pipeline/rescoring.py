"""Module C - pose restoration, geometric checks (PoseBusters), GNINA scoring,
pose selection and ligand ranking.

Quantities are kept separate and never combined:
  diffdock_confidence  pose-generation confidence (not affinity)
  CNNscore             GNINA pose-plausibility probability [0, 1]
  CNNaffinity          GNINA predicted affinity, pK units (not a free energy)
  vina                 empirical Vina score, kcal/mol (not an experimental dG)
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

GNINA_PROPS = {"minimizedAffinity": "vina", "CNNscore": "cnn_score", "CNNaffinity": "cnn_affinity",
               "CNNaffinity_variance": "cnn_affinity_variance", "CNN_VS": "cnn_vs"}


class PoseError(ValueError):
    pass


# --------------------------------------------------------------------------- poses

def restore_pose(block: str, template: Chem.Mol) -> Chem.Mol:
    """Rebuild a DiffDock pose with the prepared ligand's bond orders, charges and H.

    Heavy-atom coordinates are kept exactly; hydrogens are placed geometrically.
    """
    m = Chem.MolFromMolBlock(block, sanitize=False, removeHs=False)
    if m is None:
        raise PoseError("unparseable SDF block")
    heavy = Chem.RemoveHs(m, sanitize=False)
    tmpl = Chem.RemoveHs(template)
    if heavy.GetNumAtoms() != tmpl.GetNumAtoms():
        raise PoseError(f"heavy-atom count {heavy.GetNumAtoms()} != template {tmpl.GetNumAtoms()}")
    for b in heavy.GetBonds():
        b.SetBondType(Chem.BondType.SINGLE)
        b.SetIsAromatic(False)
    for a in heavy.GetAtoms():
        a.SetFormalCharge(0)
        a.SetIsAromatic(False)
        a.SetNoImplicit(False)
        a.SetNumExplicitHs(0)
    try:
        fixed = AllChem.AssignBondOrdersFromTemplate(tmpl, heavy)
    except ValueError as e:
        raise PoseError(f"pose topology does not match prepared ligand: {e}") from None
    if Chem.GetFormalCharge(fixed) != Chem.GetFormalCharge(tmpl):
        raise PoseError("formal charge not transferred from template")
    return Chem.AddHs(fixed, addCoords=True)


def write_sdf(mols: list[Chem.Mol], path: str | Path) -> None:
    with Chem.SDWriter(str(path)) as w:
        for m in mols:
            w.write(m)


def read_sdf(path: str | Path) -> list[Chem.Mol]:
    return [m for m in Chem.SDMolSupplier(str(path), removeHs=False) if m is not None]


# --------------------------------------------------------------------------- PoseBusters

def posebusters_check(poses_sdf: str | Path, receptor_pdb: str | Path) -> list[dict]:
    """Return per-pose {'pb_pass': bool, 'pb_failed': [check names]} in file order."""
    from posebusters import PoseBusters

    df = PoseBusters(config="dock").bust([str(poses_sdf)], None, str(receptor_pdb), full_report=False)
    checks = [c for c in df.columns if c not in ("file", "molecule", "position") and not c.startswith("mol_")]
    out = []
    for _, row in df.iterrows():
        failed = [c for c in checks if not (isinstance(row[c], (bool, np.bool_)) and row[c])]
        out.append({"pb_pass": not failed, "pb_failed": failed})
    return out


# --------------------------------------------------------------------------- GNINA

def gnina_version(exe: str) -> str:
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120)
        return (r.stdout or r.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError) as e:
        return f"unavailable ({e})"


def gnina_command(receptor: str, ligands: str, out_sdf: str, cfg: dict, mode: str = "score_only") -> list[str]:
    cmd = [cfg.get("executable", "gnina"), "-r", receptor, "-l", ligands, f"--{mode}",
           "--seed", str(cfg.get("seed", 42)), "--cpu", str(cfg.get("cpu", 4)), "-o", out_sdf]
    if not cfg.get("use_gpu", False):
        cmd.append("--no_gpu")
    return cmd + [str(x) for x in cfg.get("extra_args", [])]


def run_gnina(receptor: str | Path, poses_sdf: str | Path, out_sdf: str | Path, cfg: dict,
              mode: str = "score_only") -> tuple[dict, list[str]]:
    """Score (mode score_only) or locally minimise (mode minimize) existing poses; never re-docks.
    Returns ({pose name: scores}, command)."""
    cmd = gnina_command(str(receptor), str(poses_sdf), str(out_sdf), cfg, mode)
    log = Path(out_sdf).with_suffix(".log")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=float(cfg.get("timeout_s", 1800)))
    log.write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    if r.returncode != 0 or not Path(out_sdf).exists():
        raise RuntimeError(f"gnina failed (exit {r.returncode}); see {log}")
    scores = {}
    for m in Chem.SDMolSupplier(str(out_sdf), removeHs=False, sanitize=False):
        if m is None:
            continue
        scores[m.GetProp("_Name")] = {v: float(m.GetProp(k)) for k, v in GNINA_PROPS.items() if m.HasProp(k)}
    return scores, cmd


def minimize_poses(receptor: str | Path, poses_sdf: str | Path, out_sdf: str | Path, templates: dict,
                   cfg: dict) -> tuple[dict, list[str]]:
    """GNINA local minimisation (rigid receptor, flexible ligand torsions/position) of each pose.

    GNINA writes through OpenBabel, which may reorder atoms and re-perceive bonds, so every
    minimised pose is rebuilt on its template (bond orders/charges of the prepared ligand).
    Returns ({pose name: minimised Mol}, command)."""
    _, cmd = run_gnina(receptor, poses_sdf, out_sdf, cfg, mode="minimize")
    out = {}
    for block in Path(out_sdf).read_text().split("$$$$\n"):
        if not block.strip():
            continue
        name = block.splitlines()[0].strip()
        m = restore_pose(block, templates[name])
        m.SetProp("_Name", name)
        out[name] = m
    if set(out) != set(templates):
        raise RuntimeError(f"gnina --minimize returned {len(out)} poses for {len(templates)}")
    return out, cmd


# --------------------------------------------------------------------------- geometry helpers

def heavy_coords(m: Chem.Mol) -> np.ndarray:
    pos = m.GetConformer().GetPositions()
    return pos[[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum() > 1]]


def rmsd_to_reference(pose: Chem.Mol, ref: Chem.Mol) -> float | None:
    """Symmetry-aware heavy-atom RMSD without alignment; None if different molecules."""
    p, r = Chem.RemoveHs(pose), Chem.RemoveHs(ref)
    if Chem.MolToInchiKey(p)[:14] != Chem.MolToInchiKey(r)[:14]:
        return None
    try:
        return float(rdMolAlign.CalcRMS(p, r))
    except RuntimeError:  # e.g. different tautomer drawing: no bond-order substructure match
        return None


def centroid_distance(pose: Chem.Mol, ref: Chem.Mol) -> float:
    return float(np.linalg.norm(heavy_coords(pose).mean(0) - heavy_coords(ref).mean(0)))


def min_distance(pose: Chem.Mol, coords: list) -> float | None:
    if not coords:
        return None
    d = np.linalg.norm(heavy_coords(pose)[:, None, :] - np.asarray(coords)[None, :, :], axis=-1)
    return float(d.min())


# --------------------------------------------------------------------------- selection / ranking

def select_pose(poses: list[dict], require_pb: bool = True,
                max_site_distance_A: float | None = None) -> tuple[dict | None, list[str]]:
    """Pick the pose with highest CNNscore among those passing PoseBusters (and inside the
    active site when max_site_distance_A and site_distance_A are available).

    Ties are broken by DiffDock rank. If no pose passes, the best CNNscore pose
    is returned with a warning (when require_pb is set).
    """
    scored = [p for p in poses
              if all(isinstance(p.get(k), float) and math.isfinite(p[k]) for k in ("cnn_score", "cnn_affinity", "vina"))]
    if not scored:
        return None, ["no pose could be scored"]
    ok = [p for p in scored if p.get("pb_pass")] if require_pb else scored
    warns = []
    if not ok:
        ok = scored
        warns.append("no pose passed all PoseBusters checks; selected pose is geometrically questionable")
    if max_site_distance_A is not None and any(p.get("site_distance_A") is not None for p in ok):
        in_site = [p for p in ok if p.get("site_distance_A") is not None and p["site_distance_A"] <= max_site_distance_A]
        top_any = max(ok, key=lambda p: (p["cnn_score"], -p["diffdock_rank"]))
        if in_site:
            if top_any not in in_site:
                warns.append(f"highest-CNNscore pose was outside active site ({top_any['site_distance_A']:.1f} A > "
                             f"{max_site_distance_A:g} A); selected best in-site pose")
            ok = in_site
        else:
            closest = min(p["site_distance_A"] for p in ok if p.get("site_distance_A") is not None)
            warns.append(f"no pose within {max_site_distance_A:g} A of the reference site (closest {closest:.1f} A)")
    best = max(ok, key=lambda p: (p["cnn_score"], -p["diffdock_rank"]))
    return best, warns


def _ranks(values: list[float], descending: bool) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=descending)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = np.array(_ranks(a, False)), np.array(_ranks(b, False))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def rank_ligands(rows: list[dict], cfg: dict) -> tuple[list[dict], dict]:
    """Rank by CNNaffinity of the selected pose (higher pK first); report Vina rank alongside."""
    ranked = [r for r in rows if r.get("cnn_affinity") is not None]
    unranked = [r for r in rows if r.get("cnn_affinity") is None]
    cnn_r = _ranks([r["cnn_affinity"] for r in ranked], descending=True)
    vina_r = _ranks([r["vina"] for r in ranked], descending=False)  # more negative = better
    tol = max(1, math.ceil(len(ranked) * float(cfg.get("rank_disagreement_fraction", 0.34))))
    for r, cr, vr in zip(ranked, cnn_r, vina_r):
        r["rank"], r["vina_rank"] = cr, vr
        ha = r.get("heavy_atoms") or 0
        r["le_vina"] = round(-float(r["vina"]) / ha, 3) if ha > 0 and r.get("vina") is not None else None
        if len(ranked) >= 3 and abs(cr - vr) >= tol:
            r["warnings"].append(f"CNNaffinity rank {cr:g} vs Vina rank {vr:g} disagree")
    ranked.sort(key=lambda r: r["rank"])

    # artefact flags
    if ranked:
        med = float(np.median([r["heavy_atoms"] for r in ranked]))
        for r in ranked:
            if len(ranked) >= 3 and r["heavy_atoms"] > 1.5 * med:
                r["warnings"].append("much larger than library median: scores are size-biased")
    for r in ranked:
        if r.get("formal_charge"):
            r["warnings"].append(f"net charge {r['formal_charge']:+d}: electrostatics/desolvation poorly captured")
        md = r.get("min_dist_metal")
        if md is not None and md < float(cfg.get("metal_contact_A", 3.0)):
            r["warnings"].append(f"pose within {md:.2f} A of a metal ion: coordination not reliably scored")

    stats = {
        "n_ranked": len(ranked), "n_unranked": len(unranked),
        "spearman_cnnaffinity_vs_vina": spearman([r["cnn_affinity"] for r in ranked], [-r["vina"] for r in ranked]),
        "note": "Spearman between CNNaffinity (pK, higher=better) and -Vina (higher=better); None if <3 ligands.",
    }
    return ranked + unranked, stats
