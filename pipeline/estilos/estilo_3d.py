"""3D figure style for a docked pose (PyMOL script; registers the `estilo3d` command).

Pocket surface coloured by element (C white, O red, N blue, S yellow, polar H green),
ligand and pocket side chains as white sticks, bold one-letter residue labels, possible
polar contacts as dashes (PyMOL geometry: NOT confirmed H-bonds), white background, camera
looking from the solvent into the pocket.

In PyMOL (or via the MCP `do` tool):
  run estilos/estilo_3d.py
  estilo3d lig_<id> [, receptor=receptor] [, receptor_pdb=results_X/interactions/receptor_pH7.4.pdb]
receptor_pdb (protonated) is optional; it is only needed for the green polar hydrogens.
"""
import numpy as np
from pymol import cmd

AA = dict(ALA="A", ARG="R", ASN="N", ASP="D", CYS="C", GLN="Q", GLU="E", GLY="G", HIS="H", ILE="I",
          LEU="L", LYS="K", MET="M", PHE="F", PRO="P", SER="S", THR="T", TRP="W", TYR="Y", VAL="V")


def _solvent_view(lig: str, env: str) -> None:
    """Camera on the ligand, looking from the solvent side into the pocket, long axis horizontal."""
    xyz = cmd.get_coords(lig)
    c = xyz.mean(0)
    z = c - cmd.get_coords("(%s and name CA) within 12 of %s" % (env, lig)).mean(0)
    z /= np.linalg.norm(z)
    ax = np.linalg.svd(xyz - c)[2][0]
    x = ax - ax.dot(z) * z
    x /= np.linalg.norm(x)
    rot = np.array([x, np.cross(z, x), z])                    # model -> camera, row-wise
    cmd.zoom(lig, 8)
    v = list(cmd.get_view())
    v[0:9] = rot.T.flatten().tolist()                         # PyMOL stores it column-major
    v[12:15] = c.tolist()
    cmd.set_view(v)


def estilo3d(ligante, receptor="receptor", receptor_pdb="", raio_superficie=8.0, raio_sitio=4.0,
             cor_ligante="tv_green", overlay=0, transparencia_superficie=0.72, mostrar_cartoon=1):
    L = "(model %s)" % ligante
    if int(overlay):
        cmd.enable(ligante)
        cmd.show("sticks", "%s and not elem H" % L)
        cmd.color(cor_ligante, "%s and elem C" % L)
        cmd.color("red", "%s and elem O" % L)
        cmd.color("blue", "%s and elem N" % L)
        cmd.color("yelloworange", "%s and elem S" % L)
        sitio = "byres ((model %s) and not elem H within %.1f of %s)" % (receptor, float(raio_sitio), L)
        cname = "contatos_polares_%s" % ligante
        cmd.delete(cname)
        cmd.distance(cname, "%s and elem N+O" % L, "(%s) and elem N+O" % sitio, cutoff=3.5, mode=2)
        cmd.hide("labels", cname)
        return []
    if receptor_pdb:
        cmd.delete("receptor_H")
        cmd.load(receptor_pdb, "receptor_H")
        receptor = "receptor_H"
    E = "(model %s)" % receptor
    raio_superficie, raio_sitio = float(raio_superficie), float(raio_sitio)

    cmd.hide("everything", "all")
    cmd.disable("all")
    cmd.enable(receptor)
    cmd.enable(ligante)
    cmd.bg_color("white")
    for k, val in [("ray_opaque_background", 1), ("antialias", 2), ("ambient", 0.45), ("specular", 0.22),
                   ("ray_shadows", 0), ("depth_cue", 0), ("surface_quality", 1),
                   ("transparency", float(transparencia_superficie)),
                   ("valence", 0), ("stick_radius", 0.15), ("float_labels", 1), ("label_font_id", 7),
                   ("label_size", -0.85), ("label_color", "black"), ("label_outline_color", "white"),
                   ("label_position", (0.0, 0.0, 2.2)), ("dash_color", "tv_yellow"),
                   ("dash_gap", 0.22), ("dash_length", 0.18), ("dash_radius", 0.08)]:
        cmd.set(k, val)

    if int(mostrar_cartoon):
        cmd.show("cartoon", E)
        cmd.color("gray85", E)
        cmd.set("cartoon_transparency", 0.62, E)

    # pocket surface (only the region around the ligand, so it frames the site)
    cmd.delete("superficie")
    cmd.create("superficie", "byres (%s within %.1f of %s)" % (E, raio_superficie, L))
    cmd.show("surface", "superficie")
    cmd.set("surface_color", "white", "superficie")
    cmd.color("white", "superficie")
    cmd.color("red", "superficie and elem O")
    cmd.color("blue", "superficie and elem N")
    cmd.color("yellow", "superficie and elem S")
    cmd.color("green", "superficie and elem H and neighbor elem N+O")
    cmd.set("surface_color", -1, "superficie")                # use atom colours

    # pocket side chains: white carbons, element colours, one-letter labels
    sitio = "byres (%s and not elem H within %.1f of %s)" % (E, raio_sitio, L)
    cmd.show("sticks", "(%s) and not elem H and not name N+C+O" % sitio)
    cmd.color("grey90", "(%s) and elem C" % sitio)
    cmd.color("red", "(%s) and elem O" % sitio)
    cmd.color("blue", "(%s) and elem N" % sitio)
    cmd.color("yelloworange", "(%s) and elem S" % sitio)
    names = {}
    cmd.iterate("(%s) and name CA" % sitio, "names[(chain, resi)] = resn", space={"names": names})
    cmd.label("all", "''")
    for (chain, resi), resn in names.items():
        sel = "%s and chain %s and resi %s and not elem H and not name N+C+O" % (E, chain, resi)
        atoms = []
        cmd.iterate(sel if cmd.count_atoms(sel) else "%s and chain %s and resi %s and name CA" % (E, chain, resi),
                    "atoms.append(name)", space={"atoms": atoms})
        cmd.label("%s and chain %s and resi %s and name %s" % (E, chain, resi, atoms[-1]),
                  repr("%s%s" % (AA.get(resn, resn), resi)))

    # ligand: sticks (default white carbons, or custom cor_ligante for SAR contrast)
    cmd.show("sticks", "%s and not elem H" % L)
    cmd.color(cor_ligante, "%s and elem C" % L)
    cmd.color("red", "%s and elem O" % L)
    cmd.color("blue", "%s and elem N" % L)
    cmd.color("yelloworange", "%s and elem S" % L)

    # possible polar contacts (distance + PyMOL angle estimate; not confirmed H-bonds)
    cmd.delete("contatos_polares")
    cmd.distance("contatos_polares", "%s and elem N+O" % L, "(%s) and elem N+O" % sitio, cutoff=3.5, mode=2)
    cmd.hide("labels", "contatos_polares")

    _solvent_view(L, E)
    cmd.clip("slab", 30)
    return sorted("%s%s" % (AA.get(r, r), i) for (_, i), r in names.items())


cmd.extend("estilo3d", estilo3d)
