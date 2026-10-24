"""Assign every ligand atom to a named fragment, so each interaction is attributed to the right part
of the molecule (e.g. catechol ring vs. sugar) from atom indices, never from visual guessing.

Order of precedence: user SMARTS (estudo.yaml -> fragmentos) > sugar rings > other SSSR rings >
non-ring atoms, which inherit the label of the nearest labelled atom (graph distance); H atoms
inherit the label of their heavy neighbour.
"""
from __future__ import annotations

from collections import deque

from rdkit import Chem

SUGAR_RING = Chem.MolFromSmarts("[C;X4;R]1~[C;X4;R]~[C;X4;R]~[C;X4;R]~[C;X4;R]~[O;X2;R]1")
FURANOSE_RING = Chem.MolFromSmarts("[C;X4;R]1~[C;X4;R]~[C;X4;R]~[C;X4;R]~[O;X2;R]1")


def label_atoms(mol: Chem.Mol, user_smarts: dict[str, str] | None = None) -> list[str]:
    n = mol.GetNumAtoms()
    labels: list[str | None] = [None] * n
    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]

    for name, sma in (user_smarts or {}).items():
        patt = Chem.MolFromSmarts(sma)
        if patt is None:
            raise ValueError(f"SMARTS invalido para o fragmento '{name}': {sma}")
        for k, match in enumerate(mol.GetSubstructMatches(patt)):
            tag = name if k == 0 else f"{name}_{k + 1}"
            for i in match:
                if labels[i] is None and mol.GetAtomWithIdx(i).GetAtomicNum() > 1:
                    labels[i] = tag

    sugar_atoms = set()
    for patt in (SUGAR_RING, FURANOSE_RING):
        for match in mol.GetSubstructMatches(patt):
            sugar_atoms.add(frozenset(match))
    for k, ring in enumerate(sorted(sugar_atoms, key=min), start=1):
        for i in ring:
            if labels[i] is None:
                labels[i] = f"acucar_{k}"

    rings = [r for r in mol.GetRingInfo().AtomRings() if any(labels[i] is None for i in r)]
    for k, ring in enumerate(sorted(rings, key=min), start=1):
        aromatic = all(mol.GetAtomWithIdx(i).GetIsAromatic() for i in ring)
        tag = f"anel_{k}_{'arom' if aromatic else 'alif'}{len(ring)}"
        for i in ring:
            if labels[i] is None:
                labels[i] = tag

    # non-ring heavy atoms: nearest labelled heavy atom by graph distance (BFS from all seeds)
    dist = {i: 0 for i in heavy if labels[i] is not None}
    queue = deque(sorted(dist))
    while queue:
        i = queue.popleft()
        for nb in mol.GetAtomWithIdx(i).GetNeighbors():
            j = nb.GetIdx()
            if nb.GetAtomicNum() > 1 and j not in dist:
                dist[j] = dist[i] + 1
                labels[j] = labels[i]
                queue.append(j)
    for i in heavy:
        if labels[i] is None:
            labels[i] = "cadeia"          # acyclic molecule without user SMARTS
    for a in mol.GetAtoms():
        if a.GetAtomicNum() == 1:
            nbs = a.GetNeighbors()
            labels[a.GetIdx()] = labels[nbs[0].GetIdx()] if nbs else "H"
    return labels  # type: ignore[return-value]


def describe(mol: Chem.Mol, labels: list[str]) -> dict[str, dict]:
    """label -> {atoms, smiles}: lets a human check that 'anel_3_arom6' really is the catechol."""
    out: dict[str, dict] = {}
    for i, lab in enumerate(labels):
        if mol.GetAtomWithIdx(i).GetAtomicNum() > 1:
            out.setdefault(lab, {"atoms": []})["atoms"].append(i)
    for lab, d in out.items():
        d["smiles"] = Chem.MolFragmentToSmiles(mol, d["atoms"], canonical=True)
    return out


def fragment_of(labels: list[str], atom_indices) -> str:
    return "+".join(sorted({labels[i] for i in atom_indices}))
