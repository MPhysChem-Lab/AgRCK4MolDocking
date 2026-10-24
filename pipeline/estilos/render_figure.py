"""Didactic 3D figure from a YAML spec (open-source PyMOL, headless, one ray trace, optional legend bar).

  python render_figure.py spec.yaml        (headless PyMOL as a library; spec paths relative to the spec file)

Spec:
  saida: ../figuras/Fig_redocking.png
  receptor: ../inputs/4EY6.pdb
  cadeia: A
  cocristal: {resn: GNT, cor: forest, legenda: "Cristalográfico GNT A 604"}     # optional
  ligantes:
    - {arquivo: ../results/poses/galantamina/pose_08_min.sdf, nome: galantamina, cor: cyan, legenda: "Redocking"}
  residuos: {86: "Trp86 (CAS)", 202: "Glu202"}          # sticks + labels
  cores_residuos: {salmon: [86, 202], slate: [286]}      # carbon colour per residue group
  contatos: [[galantamina, 202]]                          # only pairs confirmed by ProLIF (E5)
  tamanho: [1200, 720]

Every object is checked (require_objects) and recorded in figuras_manifest.json. No pixel of the
rendered image is ever edited except appending the legend bar below it.
"""
import sys
from pathlib import Path

import pymol
import yaml

pymol.finish_launching(["pymol", "-qc"])
from pymol import cmd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks.figure_check import pymol_is_open_source, require_objects, write_manifest  # noqa: E402

RESERVED = {"x", "q", "all", "none", "enabled", "visible", "center", "origin"}


def obj(name: str) -> str:
    n = "lig_" + "".join(c if c.isalnum() else "_" for c in str(name))
    assert n not in RESERVED
    return n


def scene() -> None:
    cmd.reinitialize()
    for k, v in dict(bg_rgb="white", ray_opaque_background=1, orthoscopic=1, depth_cue=0, antialias=2,
                     ray_trace_mode=1, ray_trace_gain=0.06, ray_shadows=0, specular=0.25, ambient=0.48,
                     direct=0.65, valence=0, label_font_id=7, label_size=-1.0, label_color="black",
                     label_outline_color="white", label_position=(0.0, 0.0, 8.0), dash_gap=0.22,
                     dash_length=0.18, dash_radius=0.09, dash_color="tv_yellow",
                     cartoon_transparency=0.62).items():
        cmd.set(k, v)


def legend(png: Path, items: list) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        try:
            font = ImageFont.truetype("arialbd.ttf", 18)
        except OSError:
            font = ImageFont.load_default()
    im = Image.open(png).convert("RGB")
    w, h = im.size
    bar = 40 * ((len(items) + 1) // 2) + 20
    out = Image.new("RGB", (w, h + bar), "white")
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    d.line([(25, h + 2), (w - 25, h + 2)], fill=(200, 200, 200), width=2)
    for i, (rgb, text) in enumerate(items):
        x0, y0 = 30 + (i % 2) * (w // 2 - 10), h + 12 + (i // 2) * 40
        d.rectangle([x0, y0, x0 + 22, y0 + 22], fill=tuple(int(255 * c) for c in rgb), outline=(60, 60, 60), width=2)
        d.text((x0 + 30, y0 - 1), text, fill=(25, 25, 25), font=font)
    out.save(png, dpi=(300, 300))


def main(spec_path: str) -> None:
    ok, build = pymol_is_open_source()
    if not ok:
        raise SystemExit(f"PyMOL não open-source ({build}): instale pymol-open-source; não renderize com marca d'água")
    sp = Path(spec_path).resolve()
    s = yaml.safe_load(sp.read_text(encoding="utf-8"))
    rel = lambda p: (sp.parent / p).resolve()
    out = rel(s["saida"])
    out.parent.mkdir(parents=True, exist_ok=True)
    from checks.state import reopen
    reopen(out, "E5")              # a new or changed figure must pass E5 again
    scene()
    cmd.load(str(rel(s["receptor"])), "rec")
    cmd.remove(f"rec and not chain {s.get('cadeia', 'A')}")
    items, objects = [], ["rec"]
    cc = s.get("cocristal")
    if cc:
        cmd.extract("ref_cristal", f"rec and resn {cc['resn']}")
        cmd.show("sticks", "ref_cristal")
        cmd.util.cbag("ref_cristal")
        cmd.color(cc.get("cor", "forest"), "ref_cristal and elem C")
        objects.append("ref_cristal")
        items.append((cmd.get_color_tuple(cc.get("cor", "forest")), cc.get("legenda", cc["resn"])))
    cmd.remove("rec and not polymer.protein")
    cmd.hide("everything", "rec")
    cmd.show("cartoon", "rec")
    cmd.color("gray85", "rec")
    res = {str(k): v for k, v in (s.get("residuos") or {}).items()}
    if res:
        sel = "rec and resi " + "+".join(res)
        cmd.show("sticks", f"({sel}) and not name N+C+O")
        cmd.set("stick_radius", 0.13, sel)
        cmd.util.cbaw(sel)
        for color, ids in (s.get("cores_residuos") or {}).items():
            cmd.color(color, "rec and resi " + "+".join(map(str, ids)) + " and elem C")
        for resi, text in res.items():
            cmd.label(f"rec and resi {resi} and name CA", f'"{text}"')
    for lg in s.get("ligantes", []):
        o = obj(lg["nome"])
        cmd.load(str(rel(lg["arquivo"])), o)
        cmd.remove(f"{o} and hydro and not (neighbor (elem N+O))")
        cmd.show("sticks", o)
        cmd.set("stick_radius", 0.24, o)
        cmd.util.cbag(o)
        cmd.color(lg.get("cor", "tv_green"), f"{o} and elem C")
        objects.append(o)
        items.append((cmd.get_color_tuple(lg.get("cor", "tv_green")), lg.get("legenda", lg["nome"])))
    for i, (lig, resi) in enumerate(s.get("contatos") or []):
        cmd.distance(f"hb{i}", f"model {obj(lig)} and elem N+O", f"rec and resi {resi} and elem N+O", 3.6, mode=2)
        cmd.hide("labels", f"hb{i}")
    require_objects(cmd, objects)
    focus = " or ".join(f"model {o}" for o in objects if o != "rec")
    cmd.orient(focus)
    cmd.zoom(focus, buffer=float(s.get("margem", 3.2)))
    cmd.clip("slab", 38)
    w, h = s.get("tamanho", [1200, 720])
    cmd.ray(int(w), int(h))
    cmd.png(str(out), dpi=300)
    legend(out, items)
    write_manifest(out, cmd, objects, note=str(sp.name))
    print(f"ok {out} objetos={objects}")


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a != "--"][0])
    cmd.quit()
