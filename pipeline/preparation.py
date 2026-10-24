"""Module A - molecular preparation and validation.

Protein: inspected and filtered line-by-line (coordinates are never modified).
Ligands: validated with RDKit; protonation/tautomer state is *recorded*, not
changed. Decisions that cannot be automated safely become warnings.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, Descriptors, FilterCatalog, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

_PAINS_PARAMS = FilterCatalog.FilterCatalogParams()
_PAINS_PARAMS.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
_PAINS_CATALOG = FilterCatalog.FilterCatalog(_PAINS_PARAMS)

WATERS = {"HOH", "WAT", "DOD", "H2O"}
METALS = {"LI", "NA", "K", "MG", "CA", "MN", "FE", "CO", "NI", "CU", "ZN", "CD",
          "HG", "SR", "BA", "CS", "RB", "AL", "GA", "PT", "AU", "AG", "PB", "W", "MO", "V", "CR"}
# HETATM residues that are part of the polymer chain (kept as protein)
MODIFIED_RESIDUES = {"MSE", "SEP", "TPO", "PTR", "CSO", "CSD", "HYP", "MLY", "KCX", "LLP", "PCA", "CME", "OCS"}

# Descriptive only: matches are reported, the molecule is never re-protonated.
IONIZABLE_SMARTS = {
    "carboxylic_acid": "[CX3](=O)[OX2H1]",
    "carboxylate": "[CX3](=O)[OX1-]",
    "aliphatic_amine_neutral": "[NX3;H2,H1,H0;!$(N[a]);!$(N[C,S,P]=[O,S,N]);!$(N#*);!$(N=*);!$(N-N);!$(N-O)]([CX4])",
    "ammonium": "[NX4+;!$(N~[O,N])]",
    "amidine_guanidine_neutral": "[NX3;!$(N[C,S]=O)][CX3]=[NX2;!$(N-O)]",
    "amidinium_guanidinium": "[NX3][CX3]=[NX3+]",
    "imidazole": "c1cnc[nH]1",
    "phenol": "c[OX2H1]",
    "sulfonic_or_sulfate": "S(=O)(=O)[OX2H1,OX1-]",
    "phosphate_phosphonate": "P(=O)[OX2H1,OX1-]",
    "tetrazole": "c1nn[nH]n1",
    "pyridine_like_N": "[nX2;r6]",
}
_IONIZABLE = {k: Chem.MolFromSmarts(v) for k, v in IONIZABLE_SMARTS.items()}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- protein

def _parse_atom(line: str) -> dict:
    return {
        "record": line[:6].strip(), "name": line[12:16].strip(), "altloc": line[16].strip(),
        "resn": line[17:20].strip(), "chain": line[21].strip(), "resi": line[22:27].strip(),
        "x": float(line[30:38]), "y": float(line[38:46]), "z": float(line[46:54]),
        "element": (line[76:78].strip() or re.sub(r"[^A-Za-z]", "", line[12:16])[:1]).upper(),
    }


def prepare_protein(pdb_path: str | Path, out_dir: str | Path, cfg: dict) -> dict:
    """Inspect a PDB and write two filtered receptor files with unchanged coordinates.

    receptor_diffdock.pdb: polymer atoms only (DiffDock models the protein alone).
    receptor_gnina.pdb:    polymer + metals/cofactors/waters kept according to cfg.
    """
    pdb_path, out_dir = Path(pdb_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = pdb_path.read_text().splitlines()
    warnings: list[str] = []

    keep_waters = cfg.get("keep_waters", False)
    keep_metals = cfg.get("keep_metals", True)
    keep_het = {h.upper() for h in cfg.get("keep_het", [])}

    polymer, gnina_extra = [], []
    het_groups: dict[tuple, dict] = {}
    n_h = n_alt = 0
    residues: dict[str, list] = {}
    missing_res = [l for l in lines if l.startswith("REMARK 465")]
    missing_atoms = [l for l in lines if l.startswith("REMARK 470")]

    for line in lines:
        if not line.startswith(("ATOM", "HETATM")):
            continue
        a = _parse_atom(line)
        if a["altloc"] not in ("", "A"):
            n_alt += 1
            continue  # keep the blank/A conformer only
        if a["altloc"] == "A":
            n_alt += 1
        if a["element"] in ("H", "D"):
            n_h += 1
        is_polymer = a["record"] == "ATOM" or a["resn"] in MODIFIED_RESIDUES
        if is_polymer:
            polymer.append(line)
            residues.setdefault(a["chain"], [])
            key = (a["resi"], a["resn"])
            if not residues[a["chain"]] or residues[a["chain"]][-1]["key"] != key:
                residues[a["chain"]].append({"key": key, "atoms": {}})
            residues[a["chain"]][-1]["atoms"][a["name"]] = (a["x"], a["y"], a["z"])
            continue
        g = het_groups.setdefault((a["resn"], a["chain"], a["resi"]),
                                  {"resn": a["resn"], "chain": a["chain"], "resi": a["resi"],
                                   "coords": [], "elements": [], "lines": []})
        g["coords"].append((a["x"], a["y"], a["z"]))
        g["elements"].append(a["element"])
        g["lines"].append(line)

    # classify whole residues: a metal is a single-atom residue (e.g. ZN, CA), not
    # a metal atom inside a larger group such as HEM, which stays "hetero"
    for g in het_groups.values():
        g["kind"] = ("water" if g["resn"] in WATERS else
                     "metal" if len(g["lines"]) == 1 and (g["elements"][0] in METALS or g["resn"] in METALS)
                     else "hetero")
        g["kept_for_gnina"] = ((g["kind"] == "water" and keep_waters) or (g["kind"] == "metal" and keep_metals)
                               or (g["kind"] == "hetero" and g["resn"] in keep_het))
        if g["kept_for_gnina"]:
            gnina_extra.extend(g["lines"])

    if not polymer:
        raise ValueError(f"{pdb_path}: no protein ATOM records found")

    # chain breaks: C(i) - N(i+1) > 2.0 A
    gaps = []
    for chain, res in residues.items():
        for r1, r2 in zip(res, res[1:]):
            c, n = r1["atoms"].get("C"), r2["atoms"].get("N")
            if c and n and sum((p - q) ** 2 for p, q in zip(c, n)) ** 0.5 > 2.0:
                gaps.append(f"{chain}:{r1['key'][1]}{r1['key'][0]}-{r2['key'][1]}{r2['key'][0]}")
    n_res = sum(len(r) for r in residues.values())
    n_his = sum(1 for r in residues.values() for x in r if x["key"][1] == "HIS")

    if n_h == 0:
        warnings.append("Protein has no hydrogens. GNINA/OpenBabel adds them without pKa-based "
                        "protonation; His tautomers, Asp/Glu/Lys/Cys states are NOT assigned "
                        f"({n_his} HIS present). Use PDB2PQR/PROPKA or similar if this matters.")
    if missing_res:
        warnings.append(f"PDB REMARK 465 lists {len(missing_res)} line(s) of missing residues (not modeled).")
    if missing_atoms:
        warnings.append(f"PDB REMARK 470 lists {len(missing_atoms)} line(s) of missing side-chain atoms (not modeled).")
    if gaps:
        warnings.append(f"Chain breaks (C-N > 2 A): {', '.join(gaps[:10])}" + (" ..." if len(gaps) > 10 else ""))
    if n_alt:
        warnings.append(f"{n_alt} atoms with alternate locations; only blank/'A' conformers kept.")
    removed_het = sorted({g["resn"] for g in het_groups.values() if g["kind"] == "hetero" and not g["kept_for_gnina"]})
    if removed_het:
        warnings.append(f"Hetero groups removed from receptor (possible cofactors/ligands): {', '.join(removed_het)}. "
                        "If any is a required cofactor, add it to preparation.keep_het in config.yaml.")
    metals = [g for g in het_groups.values() if g["kind"] == "metal"]
    if metals:
        warnings.append(f"Metal ions present: {', '.join(sorted({m['resn'] for m in metals}))} "
                        f"({'kept' if keep_metals else 'removed'} for GNINA; DiffDock receives protein only). "
                        "Vina/CNN scoring of metal coordination is unreliable.")
    nwat = sum(1 for g in het_groups.values() if g["kind"] == "water")
    if nwat:
        warnings.append(f"{nwat} waters {'kept' if keep_waters else 'removed'}; bridging waters are not modeled"
                        if not keep_waters else f"{nwat} waters kept in GNINA receptor.")

    rec_dd = out_dir / "receptor_diffdock.pdb"
    rec_gn = out_dir / "receptor_gnina.pdb"
    rec_dd.write_text("\n".join(polymer + ["TER", "END"]) + "\n")
    rec_gn.write_text("\n".join(polymer + ["TER"] + gnina_extra + ["END"]) + "\n")

    return {
        "input": str(pdb_path), "input_sha256": sha256_file(pdb_path),
        "receptor_diffdock": str(rec_dd), "receptor_diffdock_sha256": sha256_file(rec_dd),
        "receptor_gnina": str(rec_gn), "receptor_gnina_sha256": sha256_file(rec_gn),
        "chains": sorted(residues), "n_residues": n_res, "n_hydrogens": n_h, "chain_breaks": gaps,
        "hetero_groups": [{k: v for k, v in g.items() if k not in ("coords", "elements", "lines")}
                          for g in het_groups.values()],
        "metal_coords": [c for m in metals for c in m["coords"]] if keep_metals else [],
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- ligands

@dataclass
class Ligand:
    index: int
    id: str
    name: str
    mol: Chem.Mol | None = None
    status: str = "ok"
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    path: str = ""


def _read_raw(path: Path) -> list[tuple[str, Chem.Mol | None, str]]:
    """Return (name, unsanitized mol or None, parse error)."""
    out = []
    if path.suffix.lower() == ".sdf":
        for i, m in enumerate(Chem.SDMolSupplier(str(path), removeHs=False, sanitize=False)):
            name = m.GetProp("_Name").strip() if m is not None and m.HasProp("_Name") else ""
            out.append((name or f"lig{i + 1}", m, "" if m is not None else "unparseable SDF record"))
    elif path.suffix.lower() in (".smi", ".smiles", ".txt"):
        for i, line in enumerate(l for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")):
            parts = line.split()
            m = Chem.MolFromSmiles(parts[0], sanitize=False)
            out.append((parts[1] if len(parts) > 1 else f"lig{i + 1}", m,
                        "" if m is not None else f"unparseable SMILES {parts[0]}"))
    else:
        raise ValueError(f"Unsupported ligand format: {path.suffix} (use .sdf or .smi)")
    return out


def _unique_id(name: str, used: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")[:40] or "lig"  # also PyMOL-safe
    uid, k = base, 2
    while uid in used:
        uid, k = f"{base}_{k}", k + 1
    used.add(uid)
    return uid


def _has_3d(m: Chem.Mol) -> bool:
    if m.GetNumConformers() == 0:
        return False
    pos = m.GetConformer().GetPositions()
    return bool(m.GetConformer().Is3D() and abs(pos[:, 2]).max() > 1e-3)


def protonation_report(m: Chem.Mol) -> dict:
    groups = {k: len(m.GetSubstructMatches(p)) for k, p in _IONIZABLE.items()}
    return {"formal_charge": Chem.GetFormalCharge(m),
            "ionizable_groups": {k: v for k, v in groups.items() if v}}


def pains_alerts(m: Chem.Mol) -> list[str]:
    return [e.GetDescription() for e in _PAINS_CATALOG.GetMatches(m)]


def prepare_ligand(name: str, raw: Chem.Mol, index: int, uid: str, cfg: dict) -> Ligand:
    lig = Ligand(index=index, id=uid, name=name)
    m = Chem.Mol(raw)
    try:
        Chem.SanitizeMol(m)
    except Exception as e:  # valence / aromaticity errors
        lig.status, lig.error = "invalid", f"RDKit sanitization failed: {e}"
        return lig

    frags = Chem.GetMolFrags(m, asMols=True, sanitizeFrags=False)
    if len(frags) > 1:
        m = max(frags, key=lambda f: f.GetNumHeavyAtoms())
        lig.warnings.append(f"{len(frags)} fragments (salt/solvent?); kept largest ({m.GetNumHeavyAtoms()} heavy atoms).")
    if any(a.GetNumRadicalElectrons() for a in m.GetAtoms()):
        lig.warnings.append("Radical electrons present - check input structure.")

    # stereochemistry
    unspec = [si for si in Chem.FindPotentialStereo(m) if si.specified == Chem.StereoSpecified.Unspecified]
    if unspec:
        lig.warnings.append(f"{len(unspec)} unspecified stereo element(s); an arbitrary stereoisomer will be "
                            "used. Enumerate stereoisomers explicitly if relevant.")

    # 3D structure
    had_3d = _has_3d(m)
    input_smiles = Chem.MolToSmiles(Chem.RemoveHs(m))
    if had_3d:
        if any(a.GetNumImplicitHs() for a in m.GetAtoms()):
            m = Chem.AddHs(m, addCoords=True)
            lig.warnings.append("Input 3D lacked explicit hydrogens; added with RDKit (charges as provided).")
        chk = Chem.Mol(m)
        Chem.AssignStereochemistryFrom3D(chk)
        if Chem.MolToSmiles(Chem.RemoveHs(chk)) != input_smiles and not unspec:
            lig.warnings.append("3D coordinates disagree with declared stereo tags; 3D geometry kept.")
        m = chk
    else:
        m = Chem.AddHs(m)
        params = AllChem.ETKDGv3()
        params.randomSeed = int(cfg.get("embed_seed", 42))
        if AllChem.EmbedMolecule(m, params) != 0:
            lig.status, lig.error = "invalid", "3D embedding (ETKDGv3) failed"
            return lig
        if AllChem.MMFFHasAllMoleculeParams(m):
            AllChem.MMFFOptimizeMolecule(m, maxIters=2000)
        else:
            AllChem.UFFOptimizeMolecule(m, maxIters=2000)
        lig.warnings.append("No 3D input: conformer generated with ETKDGv3 + force-field cleanup (seeded).")

    # protonation / tautomers: record only
    prot = protonation_report(m)
    if prot["ionizable_groups"]:
        lig.warnings.append("Ionizable groups " + ", ".join(f"{k}x{v}" for k, v in prot["ionizable_groups"].items())
                            + f"; protonation used AS PROVIDED (net charge {prot['formal_charge']:+d}), "
                              "not predicted for pH 7.4.")
        if prot["formal_charge"] == 0 and any(
            k in prot["ionizable_groups"]
            for k in ("aliphatic_amine_neutral", "amidine_guanidine_neutral", "carboxylic_acid")
        ):
            lig.warnings.append("Neutral ionizable group(s) detected: verify dominant microspecies at assay pH "
                                "(e.g. protonated [NH+] for basic amines or [O-] for carboxylic acids).")
    enum = rdMolStandardize.TautomerEnumerator()
    enum.SetMaxTautomers(int(cfg.get("max_tautomers", 50)))
    noh = Chem.RemoveHs(m)
    n_taut = len(enum.Enumerate(noh))
    canon = Chem.MolToSmiles(enum.Canonicalize(noh))
    smiles = Chem.MolToSmiles(noh)
    if n_taut > 1:
        lig.warnings.append(f"{n_taut} tautomers enumerable; input tautomer used"
                            + ("" if canon == smiles else f" (RDKit canonical tautomer differs: {canon})") + ".")
    pains = pains_alerts(noh)
    if pains:
        lig.warnings.append(f"PAINS structural alert(s): {', '.join(pains)}.")

    lig.mol = m
    lig.mol.SetProp("_Name", uid)
    lig.info = {
        "input_name": name, "smiles": smiles, "inchikey": Chem.MolToInchiKey(noh),
        "heavy_atoms": noh.GetNumHeavyAtoms(), "mw": round(Descriptors.MolWt(noh), 2),
        "clogp": round(Descriptors.MolLogP(noh), 2), "tpsa": round(Descriptors.TPSA(noh), 2),
        "hbd": rdMolDescriptors.CalcNumHBD(noh), "hba": rdMolDescriptors.CalcNumHBA(noh),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(noh),
        "pains_alerts": pains,
        "input_had_3d": had_3d, "n_tautomers": n_taut, "canonical_tautomer": canon, **prot,
    }
    return lig


def prepare_ligands(path: str | Path, out_dir: str | Path, cfg: dict) -> list[Ligand]:
    path, out_dir = Path(path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    used: set = set()
    ligands = []
    for i, (name, raw, err) in enumerate(_read_raw(path)):
        uid = _unique_id(name, used)
        if raw is None:
            ligands.append(Ligand(index=i, id=uid, name=name, status="invalid", error=err))
            continue
        lig = prepare_ligand(name, raw, i, uid, cfg)
        if lig.mol is not None:
            lig.path = str(out_dir / f"{uid}.sdf")
            with Chem.SDWriter(lig.path) as w:
                w.write(lig.mol)
        ligands.append(lig)
    return ligands


def load_reference_ligand(path: str | Path) -> Chem.Mol:
    m = next(iter(Chem.SDMolSupplier(str(path), removeHs=False)))
    if m is None:
        raise ValueError(f"Cannot read reference ligand {path}")
    return m


# --------------------------------------------------------------------------- co-crystal references

# crystallization additives/buffers: never treated as a co-crystal ligand
ADDITIVES = {"SO4", "PO4", "GOL", "EDO", "PEG", "PG4", "PGE", "1PE", "P6G", "ACT", "ACE", "DMS", "FMT", "MPD",
             "TRS", "EPE", "MES", "BME", "IMD", "CIT", "NO3", "SCN", "NH4", "BOG", "LDA", "IPA", "EOH", "MOH"}


def cocrystal_ligands(pdb_path: str | Path, cfg: dict) -> list[dict]:
    """Hetero groups of the input PDB that look like bound ligands (not water, metal ion,
    additive or a cofactor kept in the receptor). Bond orders are unknown at this point."""
    keep_het = {h.upper() for h in cfg.get("keep_het", [])}
    exclude = ADDITIVES | {h.upper() for h in cfg.get("exclude_resn", [])}
    min_heavy = int(cfg.get("min_heavy_atoms", 6))
    groups: dict[tuple, list[str]] = {}
    for line in Path(pdb_path).read_text().splitlines():
        if not line.startswith("HETATM"):
            continue
        a = _parse_atom(line)
        if a["altloc"] not in ("", "A") or a["resn"] in WATERS | MODIFIED_RESIDUES | keep_het | exclude:
            continue
        groups.setdefault((a["resn"], a["chain"], a["resi"]), []).append(line)
    out = []
    for (resn, chain, resi), lines in groups.items():
        m = Chem.MolFromPDBBlock("\n".join(lines) + "\nEND\n", removeHs=False, sanitize=False)
        if m is not None:  # removeHs is ignored without sanitization: drop explicit H here
            m = Chem.RemoveHs(m, sanitize=False)
        if m is None or m.GetNumAtoms() < min_heavy:
            continue
        out.append({"label": f"{resn} {chain} {resi}".replace("  ", " "), "resn": resn, "chain": chain,
                    "resi": resi, "mol": m, "matched_ligand": None})
    return out


def assign_reference_bond_orders(candidates: list[dict], ligands: list[Ligand]) -> None:
    """Give each co-crystal group the bond orders/charges of an input ligand with the same
    heavy-atom graph (template matching). Unmatched groups keep the bare PDB connectivity:
    they still define the binding site but never yield an RMSD."""
    for c in candidates:
        for lig in ligands:
            if lig.status != "ok":
                continue
            tmpl = Chem.RemoveHs(lig.mol)
            if tmpl.GetNumAtoms() != c["mol"].GetNumAtoms():
                continue
            try:
                m = AllChem.AssignBondOrdersFromTemplate(tmpl, Chem.Mol(c["mol"]))
                Chem.SanitizeMol(m)
            except (ValueError, RuntimeError):
                continue
            if Chem.MolToInchiKey(m)[:14] == Chem.MolToInchiKey(tmpl)[:14]:
                m.SetProp("_Name", f"cocrystal_{c['label'].replace(' ', '_')}")
                c.update(mol=m, matched_ligand=lig.id)
                break
