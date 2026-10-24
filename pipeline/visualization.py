"""Module D - live PyMOL session through Agentic PyMOL.

The PyMOL session runs the unmodified Agentic PyMOL plugin listener. Claude
Code talks to it via the `pymol` MCP server; run.py talks to the *same*
session through agentic_pymol.client.PyMOLClient (the repo's own client), so
the scene updates after each ligand without LLM intervention.

Object names in the session:
  receptor            protein (cartoon), pocket residues as lines
  ref_ligand          reference/crystal ligand, if given (grey sticks)
  lig_<id>            selected pose (sticks, coloured by rank or identity)
  lig_<id>_poses      all DiffDock poses as states (disabled by default)
  (ligand ids contain only [A-Za-z0-9_]; see column pymol_object in ranking.csv)

CLI (for Claude or the user):
  python visualization.py launch
  python visualization.py reload   [--results results]
  python visualization.py top      [--n 1]
  python visualization.py compare  [--n 3]
  python visualization.py poses    --ligand ID
  python visualization.py contacts --ligand ID [--cutoff 4.0]
  python visualization.py polar    --ligand ID
  python visualization.py snapshot --out FILE.png
  python visualization.py check    [--results results]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = ROOT / "tools" / "agentic-pymol"
POLAR_CRITERIA = ("PyMOL find_pairs mode=1 between donor/acceptor atoms: distance <= {cutoff} A and "
                  "angle <= {angle} deg (PyMOL h-bond geometry; receptor hydrogens are implicit, so the "
                  "angle is estimated). These are POSSIBLE hydrogen bonds, not confirmed ones.")


def _client(port: int, timeout: float = 120.0):
    import logging
    import warnings
    # agentic_pymol/__init__ imports the whole MCP server; silence its schema chatter
    logging.disable(logging.INFO)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from agentic_pymol.client import PyMOLClient
    logging.disable(logging.NOTSET)
    logging.getLogger("pymol-mcp").setLevel(logging.WARNING)
    return PyMOLClient(port=port, timeout=timeout)


def pymol_name(lig_id: str) -> str:
    """PyMOL-safe object name ('-' or a leading digit break the selection language)."""
    return "lig_" + re.sub(r"[^A-Za-z0-9_]", "_", lig_id)  # ids from preparation are already safe


def _rank_color(i: int, n: int) -> list[float]:
    """Green (best) -> magenta (worst); avoids the N-blue/O-red element colours."""
    t = 0.0 if n <= 1 else i / (n - 1)
    return [round(0.1 + 0.8 * t, 3), round(0.8 - 0.6 * t, 3), round(0.1 + 0.8 * t, 3)]


IDENTITY_COLORS = ["green", "cyan", "magenta", "yellow", "salmon", "orange", "slate", "pink", "wheat",
                   "limon", "violet", "teal", "olive", "deepteal", "hotpink", "lightorange"]


class Viewer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.port = int(cfg.get("port", 9877))
        self.c = _client(self.port)
        self.color_by = cfg.get("color_by", "rank")

    # ------------------------------------------------------------ session
    def alive(self) -> bool:
        try:
            self.c.call("get_names", [], {}, tool_name="minidock.ping", timeout=5)
            return True
        except Exception:
            return False

    def ensure_running(self) -> None:
        if self.alive():
            return
        if not self.cfg.get("launch_pymol", True):
            raise RuntimeError(f"No PyMOL listener on port {self.port}; start it with "
                               "`python visualization.py launch` or the plugin menu.")
        launch(self.port)
        deadline = time.monotonic() + float(self.cfg.get("launch_timeout_s", 90))
        while time.monotonic() < deadline:
            time.sleep(1.5)
            self.c = _client(self.port)  # token file may only exist now
            if self.alive():
                return
        raise RuntimeError(f"PyMOL listener did not come up on port {self.port} (see results/pymol.log)")

    def do(self, command: str) -> str:
        return self.c.call("do", [command], {}, tool_name="minidock.do").stdout

    def exec(self, code: str, ret: str | None = None):
        return self.c.exec_code(code, ret, tool_name="minidock.exec").value

    # ------------------------------------------------------------ scene
    def init_scene(self, receptor: str, reference: str | None = None) -> None:
        self.exec(f"""
cmd.delete('all')
cmd.load({str(Path(receptor).resolve())!r}, 'receptor')
cmd.hide('everything', 'receptor')
cmd.show('cartoon', 'receptor')
cmd.color('grey80', 'receptor and elem C')
cmd.show('spheres', 'receptor and not polymer and not solvent')
cmd.set('cartoon_transparency', 0.5)
cmd.set('stick_radius', 0.2)
cmd.bg_color('white')
""")
        if reference:
            self.exec(f"""
cmd.load({str(Path(reference).resolve())!r}, 'ref_ligand')
cmd.hide('everything', 'ref_ligand'); cmd.show('sticks', 'ref_ligand')
cmd.color('grey50', 'ref_ligand and elem C')
cmd.set('all_states', 1, 'ref_ligand')  # several co-crystal references are loaded as states
cmd.orient('ref_ligand')
""")

    def add_ligand(self, lig_id: str, selected_sdf: str, all_poses_sdf: str) -> None:
        lig_id = pymol_name(lig_id)
        cutoff = float(self.cfg.get("contact_cutoff", 4.0))
        self.exec(f"""
for _n in ({lig_id!r}, {lig_id + '_poses'!r}):
    cmd.delete(_n)
cmd.load({str(Path(selected_sdf).resolve())!r}, {lig_id!r})
cmd.load({str(Path(all_poses_sdf).resolve())!r}, {lig_id + '_poses'!r}, discrete=1)
cmd.hide('everything', {lig_id!r}); cmd.show('sticks', {lig_id!r})
cmd.hide('everything', {lig_id + '_poses'!r}); cmd.show('sticks', {lig_id + '_poses'!r})
cmd.disable({lig_id + '_poses'!r})
cmd.hide('everything', '({lig_id} or {lig_id}_poses) and elem H and neighbor elem C')
cmd.show('lines', 'byres (receptor and polymer) within {cutoff} of {lig_id}')
cmd.orient({lig_id!r}); cmd.zoom({lig_id!r}, 6)
""")

    def color_ligands(self, ordered_ids: list[str]) -> None:
        ordered_ids = [pymol_name(i) for i in ordered_ids]
        n = len(ordered_ids)
        lines = []
        for i, lid in enumerate(ordered_ids):
            if self.color_by == "rank":
                lines.append(f"cmd.set_color('mdk_{lid}', {_rank_color(i, n)})")
                col = f"mdk_{lid}"
            else:
                col = IDENTITY_COLORS[i % len(IDENTITY_COLORS)]
            lines.append(f"cmd.color({col!r}, '({lid} or {lid}_poses) and elem C')")
        self.exec("\n".join(lines))

    def refresh(self, ranked: list[dict]) -> None:
        """Called after each ligand: recolour by current ranking, order objects."""
        ids = [r["ligand_id"] for r in ranked if r.get("selected_pose_path")]
        if ids:
            self.color_ligands(ids)
            names = ["receptor", "ref_ligand"] + [pymol_name(i) for i in ids]
            self.exec(f"cmd.order({' '.join(names)!r}, location='top')")

    def show_only(self, ids: list[str]) -> None:
        ids = [pymol_name(i) for i in ids]
        self.exec(f"""
_keep = set({ids!r})
for _o in cmd.get_object_list():
    if _o in ('receptor', 'ref_ligand'):
        continue
    (cmd.enable if _o in _keep else cmd.disable)(_o)
cmd.hide('lines', 'receptor')
for _o in _keep:
    cmd.show('lines', 'byres (receptor and polymer) within {float(self.cfg.get("contact_cutoff", 4.0))} of ' + _o)
cmd.orient(' or '.join(_keep)); cmd.zoom(' or '.join(_keep), 6)
""")

    def show_poses(self, lig_id: str) -> None:
        lig_id = pymol_name(lig_id)
        self.exec(f"""
cmd.enable({lig_id + '_poses'!r}); cmd.set('all_states', 1, {lig_id + '_poses'!r})
cmd.orient({lig_id + '_poses'!r})
""")

    def contacts(self, lig_id: str, cutoff: float = 4.0) -> list[dict]:
        """Residues with any heavy atom within `cutoff` A of the ligand heavy atoms."""
        lig_id = pymol_name(lig_id)
        return self.exec(f"""
import numpy as _np
_lig = cmd.get_coords('{lig_id} and not elem H')
_res = {{}}
cmd.iterate('byres (receptor and polymer and not elem H) within {cutoff} of ({lig_id} and not elem H)',
            '_res.setdefault((chain, resi, resn), 1)', space={{'_res': _res}})
_out = []
for (_ch, _ri, _rn) in _res:
    _r = cmd.get_coords(f'receptor and chain {{_ch}} and resi {{_ri}} and not elem H')
    _d = float(_np.linalg.norm(_r[:, None] - _lig[None], axis=-1).min())
    _out.append({{'chain': _ch, 'resi': _ri, 'resn': _rn, 'min_dist_A': round(_d, 2)}})
_out.sort(key=lambda r: r['min_dist_A'])
""", "_out")

    def polar(self, lig_id: str) -> dict:
        lig_id = pymol_name(lig_id)
        cutoff = float(self.cfg.get("hbond_cutoff", 3.6))
        angle = float(self.cfg.get("hbond_angle", 63.0))
        pairs = self.exec(f"""
_pairs = cmd.find_pairs('{lig_id} and (donor or acceptor)', 'receptor and (donor or acceptor)',
                        cutoff={cutoff}, mode=1, angle={angle})
_out = []
for (_o1, _i1), (_o2, _i2) in _pairs:
    _a, _b = {{}}, {{}}
    cmd.iterate(f'%{{_o1}} and index {{_i1}}', '_a.update(name=name, elem=elem, idx=index)', space={{'_a': _a}})
    cmd.iterate(f'%{{_o2}} and index {{_i2}}', '_b.update(chain=chain, resn=resn, resi=resi, name=name)', space={{'_b': _b}})
    _out.append({{'ligand_atom': f"{{_a.get('elem')}}{{_a.get('idx')}}", 'residue': f"{{_b.get('resn')}}{{_b.get('resi')}}:{{_b.get('chain')}}",
                 'residue_atom': _b.get('name'),
                 'distance_A': round(cmd.get_distance(f'%{{_o1}} and index {{_i1}}', f'%{{_o2}} and index {{_i2}}'), 2)}})
cmd.delete('{lig_id}_polar')
for (_o1, _i1), (_o2, _i2) in _pairs:   # draw exactly the reported pairs
    cmd.distance('{lig_id}_polar', f'%{{_o1}} and index {{_i1}}', f'%{{_o2}} and index {{_i2}}')
""", "_out")
        return {"criteria": POLAR_CRITERIA.format(cutoff=cutoff, angle=angle), "pairs": pairs}

    def snapshot(self, path: str | Path, width: int | None = None, height: int | None = None) -> str:
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        w = int(width or self.cfg.get("image_width", 1200))
        h = int(height or self.cfg.get("image_height", 900))
        self.exec(f"cmd.png({str(path)!r}, width={w}, height={h}, dpi=150, ray=1)")
        for _ in range(40):  # png may be written asynchronously by the GUI thread
            if path.exists() and path.stat().st_size > 0:
                break
            time.sleep(0.25)
        return str(path)

    def save_session(self, path: str | Path) -> str:
        path = Path(path).resolve()
        self.c.call("save", [str(path)], {}, tool_name="minidock.save")
        return str(path)

    def finalize(self, ranked: list[dict], out_dir: str | Path) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ids = [r["ligand_id"] for r in ranked if r.get("selected_pose_path")]
        self.refresh(ranked)
        images = []
        rank_of = {r["ligand_id"]: r.get("rank") for r in ranked}
        for lid in ids[: int(self.cfg.get("top_n_images", 3))]:
            self.show_only([lid])
            images.append(self.snapshot(out_dir / f"rank{float(rank_of[lid]):g}_{lid}.png"))
        if ids:
            self.show_only(ids[: int(self.cfg.get("top_n_images", 3))])
            images.append(self.snapshot(out_dir / "top_overlay.png"))
        session = self.save_session(out_dir / "session.pse")
        return {"images": images, "session": session}

    def check_consistency(self, ranked: list[dict]) -> list[dict]:
        """Compare coordinates of each loaded selected pose with its SDF file."""
        from rdkit import Chem
        import numpy as np
        out = []
        for r in ranked:
            if not r.get("selected_pose_path"):
                continue
            m = next(iter(Chem.SDMolSupplier(r["selected_pose_path"], removeHs=False)))
            sdf = m.GetConformer().GetPositions()
            pm = np.array(self.exec("", f"(cmd.get_coords({pymol_name(r['ligand_id'])!r}) if cmd.count_atoms("
                                        f"{pymol_name(r['ligand_id'])!r}) else __import__('numpy').zeros((0, 3))).tolist()"))
            ok = pm.shape == sdf.shape and float(np.abs(pm - sdf).max()) < 1e-3
            out.append({"ligand_id": r["ligand_id"], "pymol_object": pymol_name(r["ligand_id"]), "n_atoms_sdf": len(sdf), "n_atoms_pymol": len(pm),
                        "max_abs_diff_A": float(np.abs(pm - sdf).max()) if pm.shape == sdf.shape else None,
                        "consistent": ok})
        return out


def launch(port: int = 9877) -> subprocess.Popen:
    """Start a GUI PyMOL with the Agentic PyMOL listener (plugin loaded unmodified)."""
    log = open(ROOT / "results" / "pymol.log", "a") if (ROOT / "results").exists() else subprocess.DEVNULL
    startup = (f"/import sys; sys.path.insert(0, {str(PLUGIN_DIR)!r}); "
               f"from pymol_plugin import start_listening; start_listening({port})")
    return subprocess.Popen([sys.executable, "-m", "pymol", "-d", startup], stdout=log, stderr=log,
                            start_new_session=True, cwd=str(ROOT))


def load_ranking(results: Path) -> list[dict]:
    with open(results / "ranking.csv") as f:
        return list(csv.DictReader(f))


def main(argv=None) -> None:
    import yaml
    ap = argparse.ArgumentParser(description="MiniDock PyMOL helpers")
    ap.add_argument("action", choices=["launch", "reload", "top", "compare", "poses", "contacts",
                                       "polar", "snapshot", "check"])
    ap.add_argument("--results", default=str(ROOT / "results"))
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--ligand")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--cutoff", type=float)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config))["visualization"]
    results = Path(a.results)
    if a.action == "launch":
        v = Viewer({**cfg, "launch_pymol": True})
        v.ensure_running()
        print(f"PyMOL listening on 127.0.0.1:{v.port}")
        return
    v = Viewer(cfg)
    v.ensure_running()
    ranked = [r for r in load_ranking(results) if r.get("selected_pose_path")]
    ids = [r["ligand_id"] for r in ranked]
    if a.action == "reload":
        meta = json.loads((results / "metadata.json").read_text())
        v.init_scene(meta["protein"]["receptor_gnina"], meta.get("reference_ligand_path"))
        for r in ranked:
            v.add_ligand(r["ligand_id"], r["selected_pose_path"], r["all_poses_path"])
        v.refresh(ranked)
        print(f"loaded {len(ranked)} ligands")
    elif a.action in ("top", "compare"):
        n = a.n if a.action == "top" else (a.n if a.n > 1 else 3)
        v.show_only(ids[:n])
        print(json.dumps([{k: r[k] for k in ("rank", "ligand_id", "cnn_affinity", "cnn_score", "vina")}
                          for r in ranked[:n]], indent=1))
    elif a.action == "poses":
        v.show_poses(a.ligand)
    elif a.action == "contacts":
        print(json.dumps(v.contacts(a.ligand or ids[0], a.cutoff or float(cfg.get("contact_cutoff", 4.0))), indent=1))
    elif a.action == "polar":
        print(json.dumps(v.polar(a.ligand or ids[0]), indent=1))
    elif a.action == "snapshot":
        print(v.snapshot(a.out or results / "visualizations" / "snapshot.png"))
    elif a.action == "check":
        print(json.dumps(v.check_consistency(ranked), indent=1))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
