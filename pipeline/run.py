#!/usr/bin/env python
"""MiniDock orchestrator: PDB + ligands -> RDKit -> DiffDock API -> GNINA -> ranking -> PyMOL.

python run.py --protein inputs/protein.pdb --ligands inputs/ligands.sdf --poses 5 --visualize
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from importlib import metadata as im
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rdkit import Chem
from rdkit.Chem import rdMolAlign

import preparation as prep
import rescoring as rs
from diffdock_client import DiffDockClient, DiffDockError
from visualization import pymol_name

ROOT = Path(__file__).resolve().parent
PIPELINE_VERSION = "1.4"   # bump when pose processing/selection changes: invalidates resumed records

RANK_COLUMNS = ["rank", "ligand_id", "name", "status", "selected_pose", "diffdock_confidence", "cnn_score",
                "cnn_affinity", "cnn_affinity_variance", "vina", "vina_rank", "le_vina", "posebusters_pass",
                "n_poses", "n_poses_pb_pass", "n_poses_in_site", "rmsd_to_reference", "site_distance_A",
                "reference", "heavy_atoms", "formal_charge", "smiles", "warnings", "error", "pymol_object",
                "selected_pose_path", "all_poses_path", "diffdock_response"]
POSE_COLUMNS = ["ligand_id", "diffdock_rank", "diffdock_confidence", "pose_valid", "pose_error", "pb_pass",
                "pb_failed", "cnn_score", "cnn_affinity", "cnn_affinity_variance", "vina", "rmsd_to_reference",
                "rmsd_to_reference_diffdock", "site_distance_A", "min_shift_A", "selected", "pose_path",
                "raw_pose_path"]
UNITS = {"diffdock_confidence": "DiffDock confidence (log-odds-like; NOT affinity)",
         "cnn_score": "GNINA CNNscore, pose plausibility probability [0,1]",
         "cnn_affinity": "GNINA CNNaffinity, predicted pK (not a free-energy calculation)",
         "vina": "Vina empirical score, kcal/mol (not an experimental dG)",
         "le_vina": "Ligand Efficiency (-Vina / heavy_atoms), kcal/mol per heavy atom",
         "n_poses_in_site": "number of PoseBusters-valid poses within max_site_distance_A of reference site",
         "rmsd_to_reference": "heavy-atom symmetry-aware RMSD to reference ligand, A (no alignment); "
                              "only when the docked ligand is the same molecule as the reference",
         "site_distance_A": "centroid distance to the nearest reference ligand, A",
         "rmsd_to_reference_diffdock": "as rmsd_to_reference, for the DiffDock pose before GNINA minimisation",
         "min_shift_A": "heavy-atom RMSD between a DiffDock pose and its GNINA-minimised pose, A",
         "reference": "reference used: --reference-ligand file or co-crystal group 'RESN chain resi' of the input PDB"}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fmt(x, nd=3):
    return "" if x is None else (round(x, nd) if isinstance(x, float) else x)


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("; ".join(r[c]) if isinstance(r.get(c), list) else fmt(r.get(c))) for c in cols})
    tmp.replace(path)


def versions(cfg: dict) -> dict:
    v = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in ("rdkit", "posebusters", "numpy", "requests", "pymol-open-source-whl", "agentic-pymol", "mcp"):
        try:
            v[pkg] = im.version(pkg)
        except im.PackageNotFoundError:
            v[pkg] = None
    try:
        v["agentic-pymol_commit"] = subprocess.run(["git", "-C", str(ROOT / "tools" / "agentic-pymol"), "rev-parse",
                                                   "HEAD"], capture_output=True, text=True).stdout.strip() or None
    except OSError:
        v["agentic-pymol_commit"] = None
    v["gnina"] = rs.gnina_version(cfg["gnina"].get("executable", "gnina"))
    return v


# --------------------------------------------------------------------------- per-ligand

def process_ligand(lig: prep.Ligand, ctx: dict) -> tuple[dict, list[dict]]:
    cfg, out = ctx["cfg"], ctx["out"]
    row = {"ligand_id": lig.id, "name": lig.name, "status": lig.status, "error": lig.error,
           "warnings": list(lig.warnings), "smiles": lig.info.get("smiles"),
           "heavy_atoms": lig.info.get("heavy_atoms"), "formal_charge": lig.info.get("formal_charge")}
    if lig.status != "ok":
        return row, []
    ldir = out / "poses" / lig.id
    ldir.mkdir(parents=True, exist_ok=True)

    # B. DiffDock
    res = ctx["diffdock"].dock(ctx["protein_text"], Path(lig.path).read_text(), ctx["num_poses"])
    row["diffdock_response"] = os.path.relpath(res.cache_file, out)
    log(f"  DiffDock: {len(res.poses)} poses ({'cache' if res.from_cache else 'API'}), "
        f"confidence {[round(c, 2) for c in res.confidences]}")

    # restore poses (bond orders/charges/H from prepared ligand; coordinates kept)
    poses, mols = [], []
    for k, (block, conf) in enumerate(zip(res.poses, res.confidences), start=1):
        raw_path = ldir / f"raw_pose_{k:02d}.sdf"
        raw_path.write_text(block if block.rstrip().endswith("$$$$") else block.rstrip("\n") + "\n$$$$\n")
        p = {"ligand_id": lig.id, "diffdock_rank": k, "diffdock_confidence": conf,
             "raw_pose_path": str(raw_path), "pose_valid": True, "pose_error": ""}
        try:
            m = rs.restore_pose(block, lig.mol)
        except rs.PoseError as e:
            p.update(pose_valid=False, pose_error=str(e))
            poses.append(p)
            continue
        m.SetProp("_Name", f"{lig.id}_pose{k:02d}")
        m.SetProp("diffdock_rank", str(k))
        m.SetProp("diffdock_confidence", f"{conf:.4f}")
        p["pose_path"] = str(ldir / f"pose_{k:02d}.sdf")
        rs.write_sdf([m], p["pose_path"])
        p["_mol"] = m
        poses.append(p)
        mols.append(m)
    valid = [p for p in poses if p["pose_valid"]]
    if not valid:
        raise RuntimeError("no DiffDock pose could be mapped onto the prepared ligand")
    all_sdf = ldir / "all_poses.sdf"
    rs.write_sdf(mols, all_sdf)

    # C0. optional GNINA local minimisation (gnina.minimize): rigid receptor, no re-docking
    eval_sdf = all_sdf
    if cfg["gnina"].get("minimize", False):
        for p in valid:
            p["rmsd_to_reference_diffdock"] = min_rmsd(p["_mol"], ctx["refs"])
        mins, mcmd = rs.minimize_poses(ctx["protein"]["receptor_gnina"], all_sdf, ldir / "gnina_minimized.sdf",
                                       {p["_mol"].GetProp("_Name"): p["_mol"] for p in valid}, cfg["gnina"])
        ctx["gnina_minimize_command"] = " ".join(mcmd)
        for p in valid:
            mm = mins[p["_mol"].GetProp("_Name")]
            for k in ("diffdock_rank", "diffdock_confidence"):
                mm.SetProp(k, p["_mol"].GetProp(k))
            p["min_shift_A"] = float(rdMolAlign.CalcRMS(Chem.RemoveHs(mm), Chem.RemoveHs(p["_mol"])))
            p["pose_path"] = str(ldir / f"pose_{p['diffdock_rank']:02d}_min.sdf")
            rs.write_sdf([mm], p["pose_path"])
            p["_mol"] = mm
        eval_sdf = ldir / "all_poses_min.sdf"
        rs.write_sdf([p["_mol"] for p in valid], eval_sdf)
        shifts = sorted(p["min_shift_A"] for p in valid)
        log(f"  GNINA minimisation: shift DiffDock -> minimised median {shifts[len(shifts) // 2]:.2f} A")

    # C. geometry checks + GNINA score_only (on the minimised poses when gnina.minimize)
    pb_rows = rs.posebusters_check(eval_sdf, ctx["protein"]["receptor_gnina"])
    if len(pb_rows) != len(valid):
        raise RuntimeError(f"PoseBusters returned {len(pb_rows)} rows for {len(valid)} poses")
    for p, pb in zip(valid, pb_rows):
        p.update(pb)
    scores, gcmd = rs.run_gnina(ctx["protein"]["receptor_gnina"], eval_sdf, ldir / "gnina_scored.sdf", cfg["gnina"])
    ctx["gnina_command"] = " ".join(gcmd)
    for p in valid:
        p.update(scores.get(p["_mol"].GetProp("_Name"), {}))
        p["rmsd_to_reference"] = min_rmsd(p["_mol"], ctx["refs"])
        p["site_distance_A"] = nearest_reference(p["_mol"], ctx["refs"])["site_distance_A"]

    max_site_d = cfg["selection"].get("max_site_distance_A")
    max_site_d = float(max_site_d) if max_site_d is not None else None
    best, warns = rs.select_pose(valid, cfg["selection"].get("require_posebusters_pass", True), max_site_d)
    row["warnings"] += warns
    for p in poses:
        p["selected"] = p is best
    if best is None:
        row.update(status="failed", error="no scorable pose")
        return row, poses
    m = Chem.Mol(best["_mol"])
    for k in ("cnn_score", "cnn_affinity", "cnn_affinity_variance", "vina"):
        if best.get(k) is not None:
            m.SetProp(k, f"{best[k]:.4f}")
    sel = ldir / "selected.sdf"
    rs.write_sdf([m], sel)
    n_in_site = sum(1 for p in valid if p.get("pb_pass")
                    and (max_site_d is None or p.get("site_distance_A") is None or p["site_distance_A"] <= max_site_d))
    row.update({
        "selected_pose": best["diffdock_rank"], "diffdock_confidence": best["diffdock_confidence"],
        "cnn_score": best.get("cnn_score"), "cnn_affinity": best.get("cnn_affinity"),
        "cnn_affinity_variance": best.get("cnn_affinity_variance"), "vina": best.get("vina"),
        "posebusters_pass": best.get("pb_pass"), "n_poses": len(poses),
        "n_poses_pb_pass": sum(1 for p in valid if p.get("pb_pass")),
        "n_poses_in_site": n_in_site,
        "rmsd_to_reference": best.get("rmsd_to_reference"),
        **nearest_reference(m, ctx["refs"]),
        "min_dist_metal": rs.min_distance(m, ctx["protein"]["metal_coords"]),
        "selected_pose_path": str(sel), "all_poses_path": str(eval_sdf),
        "pymol_object": pymol_name(lig.id),
    })
    if best["diffdock_confidence"] < -1.5:
        row["warnings"].append("low DiffDock confidence (< -1.5) for selected pose")
    if not best.get("pb_pass") and best.get("pb_failed"):
        row["warnings"].append("PoseBusters failed: " + ", ".join(best["pb_failed"]))
    row["warnings"] += redocking_warnings(best, valid, cfg.get("redocking", {}))
    return row, poses


def min_rmsd(m: Chem.Mol, refs: list[tuple[str, Chem.Mol]]) -> float | None:
    rmsds = [r for r in (rs.rmsd_to_reference(m, ref) for _, ref in refs) if r is not None]
    return min(rmsds) if rmsds else None


def nearest_reference(m: Chem.Mol, refs: list[tuple[str, Chem.Mol]]) -> dict:
    if not refs:
        return {"site_distance_A": None, "reference": None}
    d, label = min((rs.centroid_distance(m, ref), label) for label, ref in refs)
    return {"site_distance_A": d, "reference": label}


def redocking_warnings(best: dict, poses: list[dict], rcfg: dict) -> list[str]:
    """Redocking check: only for ligands that are the reference molecule itself."""
    if best.get("rmsd_to_reference") is None:
        return []
    cut = float(rcfg.get("rmsd_success_A", 2.0))
    top = min(p["rmsd_to_reference"] for p in poses if p.get("rmsd_to_reference") is not None)
    if best["rmsd_to_reference"] <= cut:
        return []
    if top <= cut:
        return [f"redocking: selected pose is {best['rmsd_to_reference']:.2f} A from the crystal pose (> {cut} A) "
                f"although a DiffDock pose at {top:.2f} A exists - pose selection, not sampling, failed"]
    return [f"redocking FAILED: no pose within {cut} A of the crystal pose (best {top:.2f} A); "
            "results for analogues in this site are unreliable"]


def resolve_references(a, cfg: dict, ligands: list, prep_dir: Path) -> tuple[list, dict, str | None]:
    """Reference ligands for RMSD/site distance: the --reference-ligand file, otherwise
    (redocking.auto_reference) the co-crystal ligands of the input PDB."""
    rcfg = cfg.get("redocking", {})
    if a.reference_ligand:
        ref = prep.load_reference_ligand(a.reference_ligand)
        return [(Path(a.reference_ligand).name, ref)], {"source": "file", "path": a.reference_ligand}, a.reference_ligand
    if not rcfg.get("auto_reference", True):
        return [], {"source": None}, None
    cands = prep.cocrystal_ligands(a.protein, {**cfg["preparation"], **rcfg})
    prep.assign_reference_bond_orders(cands, ligands)
    info = {"source": "co-crystal ligands of the input PDB" if cands else None,
            "rmsd_success_A": float(rcfg.get("rmsd_success_A", 2.0)),
            "candidates": [{"label": c["label"], "heavy_atoms": c["mol"].GetNumAtoms(),
                            "matched_ligand": c["matched_ligand"]} for c in cands]}
    if not cands:
        log("  no co-crystal ligand in the PDB: no redocking RMSD (give --reference-ligand if needed)")
        return [], info, None
    for c in cands:
        log(f"  co-crystal reference {c['label']} ({c['mol'].GetNumAtoms()} heavy atoms): "
            + (f"redocking RMSD for ligand '{c['matched_ligand']}'" if c["matched_ligand"]
               else "site reference only (no input ligand is the same molecule)"))
    path = prep_dir / "reference_cocrystal.sdf"
    with Chem.SDWriter(str(path)) as w:
        for c in cands:
            w.write(c["mol"])
    info["path"] = str(path)
    return [(c["label"], c["mol"]) for c in cands], info, str(path)


def fingerprint(lig: prep.Ligand, ctx: dict) -> str:
    h = hashlib.sha256(PIPELINE_VERSION.encode())
    h.update((Path(lig.path).read_bytes() if lig.path else lig.error.encode()))
    h.update(ctx["protein"]["receptor_gnina_sha256"].encode())
    h.update(ctx["protein"]["receptor_diffdock_sha256"].encode())
    h.update(json.dumps([ctx["num_poses"], ctx["cfg"]["diffdock"], ctx["cfg"]["gnina"], ctx["cfg"]["selection"],
                         ctx["cfg"].get("redocking"), ctx["reference_sha256"]], sort_keys=True).encode())
    return h.hexdigest()


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--protein", required=True)
    ap.add_argument("--ligands", required=True, help=".sdf or .smi (SMILES name per line)")
    ap.add_argument("--poses", type=int, help="DiffDock poses per ligand (default: config)")
    ap.add_argument("--reference-ligand", help="crystal ligand SDF: site distance and redocking RMSD "
                    "(default: co-crystal ligands found in the input PDB, see config redocking)")
    ap.add_argument("--visualize", action="store_true", help="update a live PyMOL session (Agentic PyMOL)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out", default=str(ROOT / "results"))
    ap.add_argument("--minimize", action="store_true",
                    help="GNINA local minimisation of every DiffDock pose before scoring (sets gnina.minimize)")
    ap.add_argument("--ph", type=float,
                    help="assay pH for PDB2PQR/PROPKA receptor protonation (overrides interactions.ph)")
    ap.add_argument("--fresh", action="store_true", help="recompute every ligand (DiffDock cache still used)")
    a = ap.parse_args(argv)

    # key file: $AGRCK_ENV_FILE, else ./.env (study workspace), else ~/.config/agrck/.env; never printed
    for env_file in (os.environ.get("AGRCK_ENV_FILE"), Path.cwd() / ".env", Path.home() / ".config" / "agrck" / ".env", ROOT / ".env"):
        if env_file and Path(env_file).is_file():
            load_dotenv(env_file)
            break
    cfg = yaml.safe_load(open(a.config))
    out = Path(a.out)
    for d in ("prepared/ligands", "poses", "visualizations", "raw/diffdock"):
        (out / d).mkdir(parents=True, exist_ok=True)
    if a.minimize:
        cfg["gnina"]["minimize"] = True
    if a.ph is not None:
        cfg.setdefault("interactions", {})["ph"] = a.ph
    num_poses = a.poses or int(cfg["diffdock"]["num_poses"])
    if not 1 <= num_poses <= 100:
        ap.error("--poses must be between 1 and 100 (API limit)")
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    # A. preparation
    log(f"Preparing protein {a.protein}")
    protein = prep.prepare_protein(a.protein, out / "prepared", cfg["preparation"])
    for w in protein["warnings"]:
        log(f"  WARNING protein: {w}")
    log(f"Preparing ligands {a.ligands}")
    ligands = prep.prepare_ligands(a.ligands, out / "prepared" / "ligands", cfg["preparation"])
    log(f"  {sum(l.status == 'ok' for l in ligands)}/{len(ligands)} ligands valid")
    refs, ref_info, ref_path = resolve_references(a, cfg, ligands, out / "prepared")

    ctx = {"cfg": cfg, "out": out, "protein": protein, "num_poses": num_poses, "refs": refs,
           "reference_sha256": hashlib.sha256("".join(Chem.MolToMolBlock(m) for _, m in refs).encode()).hexdigest()
           if refs else None,
           "protein_text": Path(protein["receptor_diffdock"]).read_text(),
           "diffdock": DiffDockClient(os.environ.get("NVIDIA_API_KEY"), cfg["diffdock"], out / "raw" / "diffdock"),
           "gnina_command": None, "gnina_minimize_command": None}

    viewer, vis_info, vis_errors = None, {}, []
    if a.visualize:
        from visualization import Viewer
        try:
            viewer = Viewer(cfg["visualization"])
            viewer.ensure_running()
            viewer.init_scene(protein["receptor_gnina"], ref_path)
            log(f"PyMOL session ready on port {viewer.port}")
        except Exception as e:
            vis_errors.append(f"PyMOL unavailable: {e}")
            log(f"  WARNING {vis_errors[-1]} - continuing without visualization")
            viewer = None

    rows, all_poses, failures = [], [], []
    for lig in ligands:
        log(f"Ligand {lig.index + 1}/{len(ligands)}: {lig.id}")
        rec_path = out / "poses" / lig.id / "record.json"
        fp = fingerprint(lig, ctx)
        if not a.fresh and rec_path.exists():
            rec = json.loads(rec_path.read_text())
            if rec.get("fingerprint") == fp and rec["row"]["status"] == "ok":
                log("  resumed from previous run")
                rows.append(rec["row"])
                all_poses += rec["poses"]
                if viewer and rec["row"].get("selected_pose_path"):
                    try:
                        viewer.add_ligand(lig.id, rec["row"]["selected_pose_path"], rec["row"]["all_poses_path"])
                    except Exception as e:
                        vis_errors.append(f"{lig.id}: {e}")
                continue
        try:
            row, poses = process_ligand(lig, ctx)
        except Exception as e:  # one failing ligand must not stop the batch; recorded in metadata
            row = {"ligand_id": lig.id, "name": lig.name, "status": "failed", "error": str(e),
                   "warnings": list(lig.warnings), "smiles": lig.info.get("smiles"),
                   "heavy_atoms": lig.info.get("heavy_atoms"), "formal_charge": lig.info.get("formal_charge")}
            poses = []
            failures.append({"ligand_id": lig.id, "stage": "docking/scoring", "error": str(e),
                             "traceback": traceback.format_exc(limit=3)})
        if row["status"] != "ok" and not any(f["ligand_id"] == lig.id for f in failures):
            failures.append({"ligand_id": lig.id, "stage": "preparation" if lig.status != "ok" else "scoring",
                             "error": row["error"]})
        for p in poses:
            p.pop("_mol", None)
        if row["status"] == "ok":
            log(f"  selected pose {row['selected_pose']}: CNNscore {row['cnn_score']:.3f}, "
                f"CNNaffinity {row['cnn_affinity']:.2f} pK, Vina {row['vina']:.2f} kcal/mol")
            rec_path.parent.mkdir(parents=True, exist_ok=True)
            rec_path.write_text(json.dumps({"fingerprint": fp, "row": row, "poses": poses}, indent=1))
        else:
            log(f"  {row['status']}: {row.get('error')}")
            rec_path.unlink(missing_ok=True)   # never resume an older result after a failure
        rows.append(row)
        all_poses += poses

        # incremental outputs + live visualization
        ranked, stats = rs.rank_ligands([dict(r, warnings=list(r["warnings"])) for r in rows], cfg["selection"])
        write_csv(out / "ranking.csv", ranked, RANK_COLUMNS)
        write_csv(out / "poses.csv", all_poses, POSE_COLUMNS)
        if viewer and row.get("selected_pose_path"):
            try:
                viewer.add_ligand(lig.id, row["selected_pose_path"], row["all_poses_path"])
                viewer.refresh(ranked)
            except Exception as e:
                vis_errors.append(f"{lig.id}: {e}")
                log(f"  WARNING visualization: {e}")

    ranked, stats = rs.rank_ligands(rows, cfg["selection"])
    write_csv(out / "ranking.csv", ranked, RANK_COLUMNS)
    write_csv(out / "poses.csv", all_poses, POSE_COLUMNS)

    inter_info = None
    if cfg.get("interactions", {}).get("enabled", False):
        import interactions
        try:
            log("Interaction diagrams (PDB2PQR/PROPKA + ProLIF)")
            inter_info = interactions.run(ranked, protein["receptor_diffdock"], out / "interactions", cfg["interactions"])
            for lid, v in inter_info["ligands"].items():
                log(f"  {lid}: {v['n_interactions']} interactions with {', '.join(v['residues']) or '-'}")
        except Exception as e:
            inter_info = {"error": f"{type(e).__name__}: {e}"}
            log(f"  WARNING interactions: {inter_info['error']}")

    if viewer:
        try:
            vis_info = viewer.finalize(ranked, out / "visualizations")
            vis_info["consistency"] = viewer.check_consistency(ranked)
            log(f"Saved {len(vis_info['images'])} images and {vis_info['session']}")
        except Exception as e:
            vis_errors.append(f"finalize: {e}")
            log(f"  WARNING visualization: {e}")

    meta = {
        "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
        "wall_time_s": round(time.monotonic() - t0, 1),
        "command": " ".join([Path(sys.executable).name] + sys.argv),
        "inputs": {"protein": a.protein, "protein_sha256": prep.sha256_file(a.protein),
                   "ligands": a.ligands, "ligands_sha256": prep.sha256_file(a.ligands)},
        "reference_ligand_path": ref_path, "reference_ligand_sha256": ctx["reference_sha256"],
        "redocking": ref_info,
        "parameters": {"num_poses": num_poses, **{k: cfg[k] for k in cfg}},
        "versions": versions(cfg), "gnina_command_example": ctx["gnina_command"],
        "gnina_minimize_command_example": ctx["gnina_minimize_command"],
        "protein": {k: v for k, v in protein.items() if k != "metal_coords"},
        "ligands": [{"id": l.id, "name": l.name, "status": l.status, "error": l.error, "warnings": l.warnings,
                     "prepared_path": l.path, "prepared_sha256": prep.sha256_file(l.path) if l.path else None,
                     **l.info} for l in ligands],
        "selected_pose_sha256": {r["ligand_id"]: prep.sha256_file(r["selected_pose_path"])
                                 for r in ranked if r.get("selected_pose_path")},
        "ranking_stats": stats, "failures": failures,
        "visualization": {**vis_info, "errors": vis_errors} if a.visualize else None,
        "interactions": inter_info,
        "units": UNITS,
        "scientific_notes": [
            "Ligands ranked by GNINA CNNaffinity of the selected pose; Vina reported separately, never combined.",
            "Pose selection: highest CNNscore among poses passing all PoseBusters 'dock' checks.",
            "DiffDock confidence measures pose-generation confidence, not binding affinity.",
            ("GNINA --minimize (rigid receptor, local) applied to every DiffDock pose, then --score_only on the "
             "minimised poses; no re-docking. Raw DiffDock poses kept in all_poses.sdf / pose_NN.sdf."
             if cfg["gnina"].get("minimize") else
             "GNINA used with --score_only on DiffDock poses: no re-docking, no minimisation."),
            "Protonation/tautomers used as provided; see per-ligand warnings.",
            "Redocking RMSD is measured against the holo receptor the reference came from (optimistic for "
            "cross-docking); computed only for ligands identical to the reference.",
            "Scores are not experimental affinities; IC50/Kd/Ki were not used or converted.",
        ],
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=1, default=str))
    ok = sum(r["status"] == "ok" for r in rows)
    log(f"Done: {ok}/{len(rows)} ligands ranked -> {out / 'ranking.csv'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
