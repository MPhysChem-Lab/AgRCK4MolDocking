"""Discovery-Studio-style 2D interaction diagram (residue discs around the ligand).

Same ProLIF interactions as interactions.py (explicit H; H-bonds need distance AND
D-H...A angle). Each interacting residue is a disc coloured by its strongest
interaction; dashed lines go to the ligand atom (H-bond, ionic) or to the centroid
of the ligand atoms involved (ring/hydrophobic groups). VdW contacts (ProLIF
VdWContact) are optional discs without lines, as in Discovery Studio.

ProLIF "Hydrophobic" is a generic hydrophobic contact; it is not split into
Discovery Studio's alkyl / pi-alkyl / pi-sigma classes.

python interactions_ds.py --pose pose.sdf --receptor results/interactions/receptor_pH7.4.pdb --out fig.png [--title T]
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D

# (legend label, colour); order = priority when a residue has several interaction types
STYLE = {
    "HB": ("Ligação de H convencional (dist. + ângulo)", "#2ca02c"),
    "Ionic": ("Ponte salina / carga atrativa", "#ff8c00"),
    "PiCation": ("π-cátion", "#ffa64d"),
    "PiStacking": ("π-π empilhado", "#d62ad6"),
    "XB": ("Halogênio", "#17bfbf"),
    "Hydrophobic": ("Hidrofóbica (ProLIF)", "#f0a0e0"),
    "VdW": ("van der Waals (contato)", "#d4f0d4"),
}
KIND = {"HBDonor": "HB", "HBAcceptor": "HB", "Cationic": "Ionic", "Anionic": "Ionic", "CationPi": "PiCation",
        "PiCation": "PiCation", "PiStacking": "PiStacking", "XBDonor": "XB", "XBAcceptor": "XB",
        "Hydrophobic": "Hydrophobic", "VdWContact": "VdW"}
ORDER = list(STYLE)
W, H, R = 1500, 1150, 40          # canvas (px) and disc radius


def _residue_label(res: str) -> str:
    name, chain = res.split(".") if "." in res else (res, "")
    return f"{name[:3]}\n{chain}:{name[3:]}" if chain else f"{name[:3]}\n{name[3:]}"


def _layout(anchors: np.ndarray, atoms: np.ndarray, center: np.ndarray, top: float) -> np.ndarray:
    """Place discs outward from their anchors, then relax overlaps (discs, ligand atoms, canvas)."""
    u = anchors - center
    n = np.linalg.norm(u, axis=1, keepdims=True)
    rng = np.random.default_rng(0)
    u = np.where(n > 1e-6, u / np.maximum(n, 1e-6), rng.normal(size=u.shape))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    target = anchors + u * 160
    pos = target + rng.normal(scale=4.0, size=target.shape)   # break ties between identical anchors
    for _ in range(800):
        f = 0.03 * (target - pos)
        for i in range(len(pos)):
            d = pos[i] - pos
            dist = np.linalg.norm(d, axis=1)
            m = (dist < 2 * R + 18) & (dist > 0)
            f[i] += (d[m] / dist[m, None] * (2 * R + 18 - dist[m, None]) * 0.5).sum(0)
            da = pos[i] - atoms
            dista = np.linalg.norm(da, axis=1)
            ma = dista < R + 34
            f[i] += (da[ma] / np.maximum(dista[ma, None], 1e-6) * (R + 34 - dista[ma, None]) * 0.5).sum(0)
        pos += f
        pos[:, 0] = np.clip(pos[:, 0], R + 6, W - R - 6)
        pos[:, 1] = np.clip(pos[:, 1], top + R + 6, H - 150 - R)
    return pos


def draw_ds(mol: Chem.Mol, rows: list[dict], path: str | Path, title: str, vdw_rows: list[dict] | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle

    m = Chem.Mol(mol)
    for a in m.GetAtoms():
        a.SetIntProp("orig_idx", a.GetIdx())
    heavy_of = {a.GetIdx(): a.GetIdx() if a.GetAtomicNum() > 1 else a.GetNeighbors()[0].GetIdx() for a in m.GetAtoms()}
    noh = Chem.RemoveHs(m)
    old2new = {a.GetIntProp("orig_idx"): a.GetIdx() for a in noh.GetAtoms()}
    AllChem.Compute2DCoords(noh)

    d = rdMolDraw2D.MolDraw2DCairo(W, H)
    o = d.drawOptions()
    o.padding = 0.16
    o.bondLineWidth = 2
    o.minFontSize = 14
    d.DrawMolecule(noh)
    d.FinishDrawing()
    img = plt.imread(io.BytesIO(d.GetDrawingText()), format="png")
    xy = np.array([[d.GetDrawCoords(i).x, d.GetDrawCoords(i).y] for i in range(noh.GetNumAtoms())])

    # one entry per (residue, interaction kind) -> target point on the ligand
    links: dict[str, list[tuple[str, np.ndarray]]] = {}
    for r in rows + (vdw_rows or []):
        kind = KIND.get(r["interaction"])
        if kind is None:
            continue
        idx = sorted({old2new[heavy_of[i]] for i in r["ligand_atoms"]})
        links.setdefault(r["residue"], []).append((kind, xy[idx].mean(0)))
    # a residue already drawn with a specific interaction does not also get a VdW disc
    links = {res: ([x for x in v if x[0] != "VdW"] or v[:1]) for res, v in links.items()}
    residues = sorted(links)
    if not residues:
        anchors = np.zeros((0, 2))
    else:
        anchors = np.array([np.mean([p for _, p in links[res]], axis=0) for res in residues])
    # keep discs off atoms and bonds: obstacles = atoms + 3 points along every bond
    obst = [xy] + [xy[[b.GetBeginAtomIdx() for b in noh.GetBonds()]] * (1 - t)
                   + xy[[b.GetEndAtomIdx() for b in noh.GetBonds()]] * t for t in (0.25, 0.5, 0.75)]
    pos = _layout(anchors, np.vstack(obst), xy.mean(0), top=70) if len(residues) else anchors

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img, extent=(0, W, H, 0), zorder=1)
    used = set()
    for res, p in zip(residues, pos):
        kinds = [k for k, _ in links[res]]
        main = min(kinds, key=ORDER.index)
        used.update(kinds)
        for k, target in links[res]:
            if k == "VdW":
                continue
            ax.plot([p[0], target[0]], [p[1], target[1]], ls=(0, (4, 3)), lw=2.2, color=STYLE[k][1], zorder=2)
        col = STYLE[main][1]
        ax.add_patch(Circle(p, R + 9, color=col, alpha=0.25, lw=0, zorder=3))      # soft halo
        ax.add_patch(Circle(p, R, color=col, ec="white", lw=1.5, zorder=4))
        ax.text(p[0], p[1], _residue_label(res), ha="center", va="center", fontsize=11.5, zorder=5,
                fontweight="bold" if main != "VdW" else "normal", linespacing=1.1)
    ax.text(W / 2, 38, title, ha="center", va="center", fontsize=15)
    handles = [Line2D([0], [0], marker="o", ls="none", markersize=13, markerfacecolor=STYLE[k][1],
                      markeredgecolor="white", label=STYLE[k][0]) for k in ORDER if k in used]
    if handles:
        ax.legend(handles=handles, loc="lower center", ncol=min(3, len(handles)), frameon=False, fontsize=12,
                  bbox_to_anchor=(0.5, 0.01))
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)

    # Recorte automático de margens brancas excessivas para máxima legibilidade em relatórios LaTeX/PDF
    try:
        from PIL import Image, ImageChops
        im = Image.open(path).convert("RGB")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bbox = ImageChops.difference(im, bg).getbbox()
        if bbox:
            l, t, r, b = bbox
            pad = 28
            cropped = im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))
            cropped.save(path, dpi=(300, 300))
    except Exception:
        pass


def pose_diagram(pose_sdf: str | Path, receptor_h: str | Path, out_png: str | Path, title: str,
                 types: list[str] | None = None, vdw: bool = True) -> list[dict]:
    """Run ProLIF on one pose against a protonated receptor and draw the diagram. Returns the rows."""
    import interactions

    protein, _ = interactions.load_protein(receptor_h)
    _, _, mol, rows, _ = interactions.ligand_interactions(pose_sdf, protein, types or interactions.DEFAULT_TYPES)
    vdw_rows = interactions.ligand_interactions(pose_sdf, protein, ["VdWContact"])[3] if vdw else None
    draw_ds(mol, rows, out_png, title, vdw_rows)
    return rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pose", required=True, help="ligand pose SDF (explicit H)")
    ap.add_argument("--receptor", required=True, help="protonated receptor PDB (e.g. interactions/receptor_pH7.4.pdb)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--no-vdw", action="store_true", help="do not draw VdW-contact discs")
    a = ap.parse_args(argv)
    rows = pose_diagram(a.pose, a.receptor, a.out, a.title or Path(a.pose).stem, vdw=not a.no_vdw)
    print(f"{a.out}: {len(rows)} interactions (cite the fragment column, never guess it from the picture)")
    for r in rows:
        ang = f" {r['DHA_angle_deg']:.0f}deg" if r.get("DHA_angle_deg") is not None else ""
        print(f"  {r['residue']:<12} {r['interaction']:<12} {r['distance_A']:.2f} A{ang}  <- {r['ligand_fragment']}")


if __name__ == "__main__":
    main()
