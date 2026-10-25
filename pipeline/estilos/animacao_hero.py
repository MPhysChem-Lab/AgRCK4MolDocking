"""Didactic ~45 s animation: quercitrin docked in the gorge of human AChE (open-source PyMOL).

Pipeline: PyMOL renders each frame; PIL composites it on a silver gradient and draws the boxed residue
labels, legend, caption bar and title/closing cards (labels are projected from 3D, so they follow the
camera). ffmpeg encodes the MP4 and the GIF preview.

Two render back-ends:
  * OpenGL (--gl, recommended: ~1-2 s/frame on an integrated GPU). PyMOL runs with a window of the frame
    size; it draws the gradient itself and the no-surface pass is matted from a black/white pair.
  * ray tracing (default; headless, CPU only, ~5-40 s/frame).

  PY=<miniconda>/envs/pymol_os/python.exe
  GL="$PY -m pymol -q -x -i -W 1280 -H 720 animacao_hero.py --"
  $GL render --gl --receptor receptor_pH7.4.pdb --pose pose_03_min.sdf --work ../../docs/anim/work --keys
        # 6 key frames + contact sheet (check first)
  $GL render --gl ... --frames 0:1350 --step 3        # every 3rd frame; run offsets 0, 1, 2 in parallel
  $PY animacao_hero.py render ...                     # same, ray-traced and headless (no --gl)
  $PY animacao_hero.py encode --work ../../docs/anim/work --out ../../docs/anim
        # writes animacao_ache_quercitrina.mp4/.avif/.gif ; ffmpeg path via --ffmpeg or $FFMPEG
  README preview without text bands: render --clean into another --work dir, then encode --suffix _limpa

Content is hypothesis-level: contacts come from the ProLIF analysis of the selected pose (receptor at pH 7.4).
"""
import argparse
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

W, H, FPS, DURATION = 1280, 720, 30, 45.0
FOV = 20.0
BAR_H = 104                     # caption bar height (px); the scene is centred in the free area above
TITLE_H = 190                   # title card height (px); the opening shot is centred in the area below it
CLOSE_H = 160                   # closing card height (px), at the bottom of the frame
LABEL_GAP = 12                  # minimum gap (px) between residue labels and the caption/closing bars
BG_TOP, BG_BOT = (234, 237, 242), (150, 156, 167)   # silver background gradient (top, bottom)
TOP_ALPHA = 0.92                # opacity of the no-surface pass (ligand + contacts) drawn over the surface
GORGE_FRONT = 3.5              # front clip (Å in front of the gorge plane): opens the near wall, keeps the ligand
CHAIN = "A"

# ---- scientific content (ProLIF, pose 03, pH 7.4) --------------------------------------------------
LIG_O_HB, LIG_H_HB = 19, 39                      # 0-based atom indices in the SDF
RING_C = [0, 1, 2, 3, 8, 9]
HB_RES = 83
PI_RES = [124, 337]
PI_REF = {124: 5.18, 337: 5.51}                  # ProLIF centroid-centroid distances (Å)
HB_REF = (3.05, 169.9)                           # ProLIF H-bond: D...A distance (Å), D-H...A angle (°)
HYDRO_RES = [74, 86, 286, 297, 338, 341]         # (Tyr124/Tyr337 appear in the pi-stacking step)
SUBSITES = [
    ("PAS", [72, 74, 124, 286, 341],
     "Sítio aniônico periférico (PAS), na entrada da garganta: Tyr72, Asp74, Tyr124, Trp286, Tyr341"),
    ("GARGALO", [124, 337, 338],
     "Gargalo da garganta: Tyr124, Tyr337 e Phe338 estreitam a passagem"),
    ("CAS", [86, 337],
     "Sítio aniônico catalítico (CAS), no fundo da garganta: Trp86 e Tyr337"),
    ("TRIADE", [203, 447, 334],
     "Tríade catalítica: Ser203, His447 e Glu334 (hidrólise da acetilcolina)"),
]
RESNAME = {72: "Tyr72", 74: "Asp74", 83: "Thr83", 86: "Trp86", 124: "Tyr124", 286: "Trp286", 297: "Phe297",
           334: "Glu334", 337: "Tyr337", 338: "Phe338", 341: "Tyr341", 203: "Ser203", 447: "His447"}

TYPE_COLORS = {                                   # surface colours by residue class (as in the hero figure)
    "aro": (0.910, 0.725, 0.353), "ali": (0.918, 0.878, 0.784), "pol": (0.773, 0.855, 0.918),
    "aci": (0.863, 0.420, 0.420), "bas": (0.435, 0.561, 0.855)}
TYPE_RES = {"aro": "PHE+TRP+TYR+HIS", "ali": "ALA+VAL+LEU+ILE+MET+PRO+GLY+CYS",
            "pol": "SER+THR+ASN+GLN", "aci": "ASP+GLU", "bas": "LYS+ARG"}
LEGEND = [("aromático", "aro"), ("alifático", "ali"), ("polar", "pol"), ("ácido", "aci"), ("básico", "bas")]
TEAL = (0.184, 0.498, 0.549)

CAPTIONS = [  # (t0, t1, text, sub)
    (0.0, 5.0, "", ""),
    (5.0, 11.0, "Aproximando da garganta da enzima, que conduz ao sítio catalítico", ""),
    (11.0, 17.0, "Superfície colorida pelo tipo de resíduo: aromáticos (ouro) revestem a garganta", ""),
] + [(17.0 + 3 * i, 20.0 + 3 * i, s[2], "") for i, s in enumerate(SUBSITES)] + [
    (29.0, 34.0, "Contatos hidrofóbicos (tracejado cinza): Asp74, Trp86, Trp286, Phe297, Phe338 e Tyr341", ""),
    (34.0, 37.0, "Empilhamento π do anel C da quercitrina com Tyr124 (5,18 Å) e Tyr337 (5,51 Å)", ""),
    (37.0, 40.0, "Ligação de H: OH do catecol (anel B) → Thr83, compatível com doador–aceptor (3,05 Å · 170°)", ""),
]


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (6 * x - 15) + 10)


def lerp(a, b, x):
    return a + (b - a) * x


def window(t, t0, t1, fade=0.5):
    """alpha of an element visible in [t0, t1] with fade-in/out"""
    if t < t0 or t > t1:
        return 0.0
    return min(1.0, (t - t0) / fade, (t1 - t) / fade)


def slerp_rot(r0, r1, x):
    """interpolate two rotation matrices through quaternions"""
    def to_q(m):
        t = np.trace(m)
        if t > 0:
            s = math.sqrt(t + 1) * 2
            return np.array([0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s])
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1 + m[i, i] - m[j, j] - m[k, k]) * 2
        q = np.zeros(4)
        q[0] = (m[k, j] - m[j, k]) / s
        q[1 + i] = 0.25 * s
        q[1 + j] = (m[j, i] + m[i, j]) / s
        q[1 + k] = (m[k, i] + m[i, k]) / s
        return q

    def to_m(q):
        w, x_, y, z = q
        return np.array([[1 - 2 * (y * y + z * z), 2 * (x_ * y - z * w), 2 * (x_ * z + y * w)],
                         [2 * (x_ * y + z * w), 1 - 2 * (x_ * x_ + z * z), 2 * (y * z - x_ * w)],
                         [2 * (x_ * z - y * w), 2 * (y * z + x_ * w), 1 - 2 * (x_ * x_ + y * y)]])
    q0, q1 = to_q(r0), to_q(r1)
    if q0 @ q1 < 0:
        q1 = -q1
    d = min(1.0, q0 @ q1)
    th = math.acos(d)
    if th < 1e-5:
        q = q0
    else:
        q = (math.sin((1 - x) * th) * q0 + math.sin(x * th) * q1) / math.sin(th)
    return to_m(q / np.linalg.norm(q))


def rot_y(a_deg):
    a = math.radians(a_deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])


def rot_x(a_deg):
    a = math.radians(a_deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


class Cam:
    """camera = rotation (rows: camera axes in model coordinates), origin, distance, slab width.

    front: front clipping plane, in Å in front of the origin (default slab/2; a small value cuts the
    near wall of the gorge open); shift_px: screen pixels the scene is moved up (default: half the
    caption bar; negative moves it down, below the title card)."""

    def __init__(self, rot, origin, vis_h, slab, front=None, shift_px=BAR_H / 2):
        self.rot, self.origin, self.vis_h, self.slab = np.array(rot, float), np.array(origin, float), vis_h, slab
        self.front = slab / 2 if front is None else front
        self.shift_px = shift_px

    @property
    def dist(self):
        return self.vis_h / (2 * math.tan(math.radians(FOV) / 2))

    @staticmethod
    def mix(a, b, x):
        return Cam(slerp_rot(a.rot, b.rot, x), a.origin + (b.origin - a.origin) * x,
                   math.exp(lerp(math.log(a.vis_h), math.log(b.vis_h), x)),
                   math.exp(lerp(math.log(a.slab), math.log(b.slab), x)),
                   lerp(a.front, b.front, x), lerp(a.shift_px, b.shift_px, x))

    def shift(self):
        """camera-space y offset that moves the scene up by shift_px pixels"""
        f = (H / 2) / math.tan(math.radians(FOV) / 2)
        return self.shift_px * self.dist / f

    def project(self, p):
        pc = self.rot @ (np.asarray(p, float) - self.origin) + np.array([0, self.shift(), -self.dist])
        f = (H / 2) / math.tan(math.radians(FOV) / 2)
        depth = -pc[2]
        return W / 2 + f * pc[0] / depth, H / 2 - f * pc[1] / depth


class Scene:
    def __init__(self, receptor, pose, gl=False, clean=False):
        from pymol import cmd
        self.cmd, self.gl, self.clean = cmd, gl, clean     # clean: no caption bar, title or closing card
        cmd.reinitialize()
        cmd.load(receptor, "rec")
        cmd.remove("rec and (hydro or not polymer.protein)")
        cmd.remove(f"rec and not chain {CHAIN}")
        cmd.load(pose, "lig")
        cmd.remove("lig and hydro and not (neighbor (elem N+O))")
        for k, v in dict(bg_rgb="white", ray_opaque_background=0, antialias=1, ray_shadows=0, depth_cue=0,
                         orthoscopic=0, field_of_view=FOV, specular=0.25, ambient=0.48, direct=0.65,
                         valence=0, surface_quality=1, ray_trace_mode=0, ray_trace_gain=0.0,
                         cartoon_fancy_helices=1, dash_gap=0.25, dash_length=0.2, dash_round_ends=1,
                         cartoon_sampling=10, stick_radius=0.15, max_threads=int(os.environ.get("RAY_THREADS", 6)),
                         sphere_quality=2, cartoon_transparency=0.0, transparency_mode=1).items():
            cmd.set(k, v)
        for n, c in TYPE_COLORS.items():
            cmd.set_color("c_" + n, list(c))
        cmd.set_color("c_teal", list(TEAL))
        cmd.set_color("c_lig", [0.93, 0.93, 0.93])
        # receptor: rainbow cartoon + separate surface copy coloured by residue type
        cmd.hide("everything", "rec")
        cmd.show("cartoon", "rec")
        cmd.spectrum("resi", "rainbow", "rec and name CA")
        cmd.spectrum("resi", "rainbow", "rec")
        cmd.create("surf", "rec")
        cmd.hide("everything", "surf")
        for n, rn in TYPE_RES.items():
            cmd.color("c_" + n, f"surf and resn {rn}")
        cmd.show("surface", "surf")
        cmd.set("surface_color", -1, "surf")
        # residues shown as sticks
        allres = sorted({r for _, rs, _ in SUBSITES for r in rs} | set(HYDRO_RES) | set(PI_RES) | {HB_RES})
        # side chains only, plus the Thr83 carbonyl (the H-bond acceptor)
        cmd.create("sites", f"rec and resi {'+'.join(map(str, allres))} and "
                            f"(not name N+C+O or (resi {HB_RES} and name C+O))")
        cmd.hide("everything", "sites")
        # ligand
        cmd.show("sticks", "lig")
        cmd.set("stick_radius", 0.22, "lig")
        cmd.color("c_lig", "lig and elem C")
        cmd.color("red", "lig and elem O")
        cmd.color("white", "lig and elem H")
        cmd.show("spheres", "lig and not elem H")
        # geometry
        self.lig = cmd.get_coords("lig and not elem H")
        self.lig_c = self.lig.mean(0)
        self.ca = cmd.get_coords("rec and name CA")
        self.com = self.ca.mean(0)
        self.build_contacts()
        self.build_cameras()

    # -- helpers -------------------------------------------------------------------------------------
    def res_xyz(self, resi, names=None, obj="rec"):
        sel = f"{obj} and resi {resi}" + (f" and name {'+'.join(names)}" if names else "")
        return self.cmd.get_coords(sel)

    def ring_centroid(self, resi):
        names = ["CG", "CD1", "CD2", "CE1", "CE2", "CZ"]
        return self.res_xyz(resi, names).mean(0)

    def build_contacts(self):
        cmd = self.cmd
        lig_all = cmd.get_coords("lig")
        # SDF index -> the object kept all atoms except non-polar H, so index by id in the original SDF
        ids = []
        cmd.iterate("lig", "ids.append(ID)", space={"ids": ids})
        id2xyz = {i: c for i, c in zip(ids, lig_all)}
        self.lig_xyz = lambda i: id2xyz[i + 1]
        o19, h39 = self.lig_xyz(LIG_O_HB), self.lig_xyz(LIG_H_HB)
        acc = [(np.linalg.norm(c - o19), n) for n, c in zip(
            *self._names("rec and resi %d and elem O" % HB_RES))]
        d, acc_name = min(acc)
        self.hb_dist, self.hb_acc = d, acc_name
        a_xyz = self.res_xyz(HB_RES, [acc_name])[0]
        u, w = o19 - h39, a_xyz - h39                   # D-H...A angle, at the hydrogen
        self.hb_angle = math.degrees(math.acos(u @ w / (np.linalg.norm(u) * np.linalg.norm(w))))
        ringc = np.mean([self.lig_xyz(i) for i in RING_C], 0)
        cmd.pseudoatom("ps_ringc", pos=ringc.tolist())
        for r in PI_RES:
            cmd.pseudoatom(f"ps_ring{r}", pos=self.ring_centroid(r).tolist())
        cmd.hide("everything", "ps_*")
        cmd.distance("d_hb", f"lig and id {LIG_O_HB + 1}", f"rec and resi {HB_RES} and name {acc_name}")
        for r in PI_RES:
            cmd.distance(f"d_pi{r}", "ps_ringc", f"ps_ring{r}")
        # hydrophobic: closest C...C pair between ligand and each residue side chain
        self.hydro_pairs = {}
        heavy_c = [(i, self.lig_xyz(i)) for i in range(len(id2xyz)) if cmd.count_atoms(f"lig and id {i + 1} and elem C")]
        for r in HYDRO_RES:
            names, xyz = self._names(f"rec and resi {r} and elem C and not name C+CA")
            best = min(((np.linalg.norm(lc - c), li, n) for li, lc in heavy_c for n, c in zip(names, xyz)))
            self.hydro_pairs[r] = best
            cmd.distance(f"d_h{r}", f"lig and id {best[1] + 1}", f"rec and resi {r} and name {best[2]}")
        cmd.hide("labels", "d_*")
        cmd.hide("everything", "d_*")
        self.pts = {"hb": (o19 + self.res_xyz(HB_RES, [acc_name])[0]) / 2}
        self.ringc = ringc

    def _names(self, sel):
        names = []
        self.cmd.iterate(sel, "names.append(name)", space={"names": names})
        return names, self.cmd.get_coords(sel)

    def build_cameras(self):
        cmd = self.cmd
        cmd.orient("rec")
        v = cmd.get_view()
        self.far_rot0 = np.array(v[0:9]).reshape(3, 3).T
        far_c = np.array(v[12:15])
        self.far_origin = far_c
        # side view of the gorge: PAS (Trp286 ring) -> CAS (Trp86 ring)
        pas = self.res_xyz(286, ["CD2", "CE2", "CE3", "CZ2", "CZ3", "CH2"]).mean(0)
        cas = self.res_xyz(86, ["CD2", "CE2", "CE3", "CZ2", "CZ3", "CH2"]).mean(0)
        mid = (pas + cas) / 2
        u = (cas - pas)
        u /= np.linalg.norm(u)
        n = np.cross(u, self.lig_c - mid)
        n /= np.linalg.norm(n)
        if n @ (mid - self.com) < 0:
            n = -n
        x = u
        y = np.cross(n, x)
        self.side_rot = np.array([x, y, n])
        self.mid, self.pas, self.cas = mid, pas, cas
        self.gorge_len = float(np.linalg.norm(cas - pas))
        # solvent view (hero-like): looks from the solvent into the pocket, ligand long axis horizontal
        c = self.lig_c
        z = c - self.ca[np.linalg.norm(self.ca - c, axis=1) < 12].mean(0)
        z /= np.linalg.norm(z)
        ax = np.linalg.svd(self.lig - c)[2][0]
        xx = ax - ax.dot(z) * z
        xx /= np.linalg.norm(xx)
        self.solv_rot = np.array([xx, np.cross(z, xx), z])
        prot_r = np.linalg.norm(self.ca - self.com, axis=1).max()
        self.far_vis_h = prot_r * (2.4 if self.clean else 3.0)    # no title card: the enzyme can fill more
        # keyframe cameras (opening shot: centred below the title card)
        self.cam_far1 = Cam(rot_y(40) @ self.far_rot0, self.com, self.far_vis_h, 400, shift_px=-TITLE_H / 2)
        self.cam_side = Cam(self.side_rot, mid, 34, 18, front=GORGE_FRONT)
        self.cam_solv = Cam(self.solv_rot, c, 26, 22)

    def site_cam(self, name):
        pts = {"PAS": self.res_xyz(286).mean(0), "GARGALO": self.res_xyz(337).mean(0),
               "CAS": self.res_xyz(86).mean(0), "TRIADE": self.res_xyz(203).mean(0)}
        # keep centre inside the slab plane by projecting on the side-view plane
        p = pts[name]
        n = self.side_rot[2]
        p = p - n * ((p - self.mid) @ n)
        return Cam(self.side_rot, p, 30, 18, front=GORGE_FRONT)

    # -- timeline ------------------------------------------------------------------------------------
    def camera(self, t):
        if t < 5:
            return Cam(rot_y(40 * (t / 5)) @ self.far_rot0, self.com, self.far_vis_h, 400, shift_px=-TITLE_H / 2)
        if t < 11:
            x = ease((t - 5) / 6)
            c = Cam.mix(self.cam_far1, self.cam_side, x)
            # keep the slab wide until the last part of the flight, then close it onto the gorge plane
            y = ease((x - 0.45) / 0.55) if x > 0.45 else 0.0
            c.slab, c.front = lerp(400, self.cam_side.slab, y), lerp(200, GORGE_FRONT, y)
            return c
        if t < 17:
            return Cam(self.side_rot, self.mid, lerp(34, 32, ease((t - 11) / 6)), 18, front=GORGE_FRONT)
        if t < 29:
            names = [s[0] for s in SUBSITES]
            k = min(int((t - 17) // 3), 3)
            prev = self.site_cam(names[k - 1]) if k > 0 else Cam(self.side_rot, self.mid, 32, 18, front=GORGE_FRONT)
            cur = self.site_cam(names[k])
            return Cam.mix(prev, cur, ease((t - 17 - 3 * k) / 1.2))
        if t < 31:
            last = self.site_cam("TRIADE")
            return Cam.mix(last, self.cam_solv, ease((t - 29) / 2))
        if t < 40:
            return Cam(rot_y(4 * math.sin((t - 31) / 9 * math.pi)) @ self.solv_rot, self.lig_c, lerp(26, 24, (t - 31) / 9), 22)
        x = (t - 40) / 5
        # closing: the scene rises above the (lower) closing card instead of the caption bar
        return Cam(rot_y(-12 + 24 * ease(x)) @ self.solv_rot, self.lig_c, lerp(24, 27, x), 22,
                   shift_px=lerp(BAR_H / 2, CLOSE_H / 2, ease((t - 40) / 1.0)))

    def state(self, t):
        s = dict(t=t)
        s["cam"] = self.camera(t)
        s["clean"] = self.clean
        if self.clean:                                    # nothing covers the frame: centre the scene
            s["cam"].shift_px = 0.0
        # cartoon / surface
        # the cartoon fades out within 1 s and the opaque surface takes over; the front clip, not
        # transparency, opens the gorge (opaque also ray-traces ~2x faster)
        if t < 11:
            s["cart_tr"], s["surf_tr"] = 0.35, None
        elif t < 17:
            s["cart_tr"] = lerp(0.35, 1.0, ease((t - 11) / 1.0))
            x = ease((t - 11) / 1.5)
            s["surf_tr"] = lerp(1.0, 0.0, x) if x > 0.02 else None
        else:
            s["surf_tr"], s["cart_tr"] = 0.0, 1.0
        if t < 5:
            s["sphere"] = 1.1
        elif t < 11:
            s["sphere"] = lerp(1.1, 0.0, ease((t - 5) / 4.5))
        else:
            s["sphere"] = 0.0
        # residues in sticks: {resi: mode}, mode teal/orange; only the current sub-site is shown
        res, labels = {}, {}
        if 17 <= t < 29:
            k = min(int((t - 17) // 3), 3)
            for r in SUBSITES[k][1]:
                res[r] = "orange" if SUBSITES[k][0] == "TRIADE" else "teal"
                labels[r] = window(t, 17 + 3 * k + 0.3, 20 + 3 * k + (0.2 if k == 3 else 1.0), 0.4)
        if 31 <= t <= 45:
            for r in HYDRO_RES + PI_RES + [HB_RES]:
                res[r] = "teal"
            tt = {r: 31.0 for r in HYDRO_RES}
            tt.update({r: 34.0 for r in PI_RES})
            tt[HB_RES] = 37.0
            for r, t0 in tt.items():
                labels[r] = min(1.0, max(0.0, (t - t0) / 0.5))
        s["res"], s["labels"] = res, labels
        # dashes: name -> (start time)
        d = {}
        for r in HYDRO_RES:
            d[f"d_h{r}"] = ("grey30", 0.075, 31.2 + 0.25 * HYDRO_RES.index(r))
        for r in PI_RES:
            d[f"d_pi{r}"] = ("magenta", 0.11, 34.2 + 0.4 * PI_RES.index(r))
        d["d_hb"] = ("tv_yellow", 0.12, 37.2)
        s["dashes"] = {k: (c, rad * min(1.0, (t - t0) / 0.6)) for k, (c, rad, t0) in d.items() if t >= t0}
        # overlays
        s["legend"] = window(t, 12.0, 40.5, 1.0)
        s["circle"] = window(t, 0.5, 5.6, 0.8) * (1.0 if t < 5 else 1 - (t - 5) / 0.6)
        s["title"] = 1.0 if t < 0.7 else window(t, 0.0, 4.6, 0.7)
        s["closing"] = window(t, 40.3, 45.01, 0.8) if t < 44.2 else 1.0
        if self.clean:
            s["title"] = s["closing"] = 0.0
        s["hb_label"] = min(1.0, max(0.0, (t - 37.6) / 0.5))
        return s

    # -- render --------------------------------------------------------------------------------------
    def apply(self, s):
        cmd = self.cmd
        cam = s["cam"]
        v = list(cmd.get_view())
        rot = cam.rot
        v[0:9] = rot.T.flatten().tolist()
        v[9:12] = [0.0, cam.shift(), -cam.dist]
        v[12:15] = cam.origin.tolist()
        v[15] = max(1.0, cam.dist - cam.front)
        v[16] = cam.dist + cam.slab - cam.front
        cmd.set_view(v)
        # cartoon
        if s["cart_tr"] >= 0.97:
            cmd.hide("cartoon", "rec")
        else:
            cmd.show("cartoon", "rec")
            cmd.set("cartoon_transparency", s["cart_tr"], "rec")
        # surface
        if s["surf_tr"] is None:
            cmd.hide("surface", "surf")
        else:
            cmd.show("surface", "surf")
            cmd.set("transparency", s["surf_tr"], "surf")
        # ligand spheres
        if s["sphere"] < 0.05:
            cmd.hide("spheres", "lig")
        else:
            cmd.show("spheres", "lig and not elem H")
            cmd.set("sphere_scale", s["sphere"], "lig")
        # residue sticks
        cmd.hide("sticks", "sites")
        for r, mode in s["res"].items():
            sel = f"sites and resi {r}"
            cmd.show("sticks", sel)
            cmd.set("stick_radius", 0.2, sel)
            col = {"teal": "c_teal", "orange": "orange"}[mode]
            cmd.color(col, f"{sel} and elem C")
            cmd.color("red", f"{sel} and elem O")
            cmd.color("blue", f"{sel} and elem N")
            cmd.color("yelloworange", f"{sel} and elem S")
        # dashes
        for n in [x for x in cmd.get_names() if x.startswith("d_")]:
            cmd.disable(n)
        for n, (c, rad) in s["dashes"].items():
            cmd.enable(n)
            cmd.show("dashes", n)
            cmd.set("dash_color", c, n)
            cmd.set("dash_radius", max(rad, 0.01), n)
            cmd.hide("labels", n)

    def render(self, s, out_png):
        """ray-trace the frame; with the surface on, also a second pass without it (ligand, contact
        residues and dashes), composited on top so the surface never hides the ligand"""
        cmd = self.cmd
        self.apply(s)
        top = top_path(out_png)
        top.unlink(missing_ok=True)
        if self.gl:
            cmd.png(str(out_png), 0, 0, ray=0)          # window size; a larger size crashes PyMOL's GL
        else:
            cmd.png(str(out_png), W, H, ray=1)
        if s["surf_tr"] is None:
            return
        # disable/enable (not hide/show): keeps the surface from being recomputed every frame
        cmd.disable("surf")
        cmd.disable("rec")
        if self.gl:
            self.gl_matte(top)
        else:
            cmd.png(str(top), W, H, ray=1)
        cmd.enable("surf")
        cmd.enable("rec")

    def gl_matte(self, out_png):
        """GL output has no alpha: render on black and on white, recover colour + alpha from the difference"""
        from PIL import Image
        cmd = self.cmd
        cmd.set("bg_gradient", 0)
        k_png = Path(out_png)
        w_png = k_png.with_name(k_png.stem + "_wht.png")
        cmd.bg_color("black")
        cmd.png(str(k_png), 0, 0, ray=0)
        cmd.bg_color("white")
        cmd.png(str(w_png), 0, 0, ray=0)
        k = np.asarray(Image.open(k_png).convert("RGB"), float)
        w = np.asarray(Image.open(w_png).convert("RGB"), float)
        a = np.clip(1 - (w - k).mean(2) / 255.0, 0, 1)
        rgb = np.clip(k / np.maximum(a[..., None], 1e-3), 0, 255) * (a[..., None] > 1e-3)
        Image.fromarray(np.dstack([rgb, a * 255]).astype(np.uint8), "RGBA").save(k_png)
        w_png.unlink(missing_ok=True)
        self.gl_background()

    def gl_background(self):
        cmd = self.cmd
        cmd.set("bg_gradient", 1)
        cmd.set("bg_rgb_top", [c / 255 for c in BG_TOP])
        cmd.set("bg_rgb_bottom", [c / 255 for c in BG_BOT])


# ---- compositing ----------------------------------------------------------------------------------
def fonts():
    from PIL import ImageFont
    base = "C:/Windows/Fonts/"

    def f(name, size):
        for p in (base + name, "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
        return ImageFont.load_default()
    return dict(cap=f("segoeui.ttf", 25), cap_small=f("segoeui.ttf", 19), lab=f("segoeuib.ttf", 18),
                title=f("segoeuib.ttf", 50), sub=f("segoeui.ttf", 26), leg=f("segoeui.ttf", 17), hb=f("segoeuib.ttf", 21))


_BG = None


def background():
    global _BG
    if _BG is None:
        from PIL import Image
        top, bot = np.array(BG_TOP), np.array(BG_BOT)
        a = np.linspace(0, 1, H)[:, None, None] ** 1.1
        g = (top * (1 - a) + bot * a) * np.ones((1, W, 1))
        _BG = Image.fromarray(g.astype(np.uint8), "RGB").convert("RGBA")
    return _BG


def wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= maxw:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def caption_text(t):
    """list of (text, alpha): each caption fades out before the next fades in, so they never overlap"""
    out = []
    for t0, t1, text, _ in CAPTIONS:
        if text:
            a = window(t, t0, t1, 0.25)
            if a > 0:
                out.append((text, a))
    return out


def bar_alpha(t):
    """opacity of the caption bar: fades in with the first caption and out under the closing card"""
    t0 = min(c[0] for c in CAPTIONS if c[2])
    t1 = max(c[1] for c in CAPTIONS if c[2])
    return window(t, t0, t1 + 0.4, 0.4)


def top_path(raw_png):
    """second render pass (no surface) of a raw frame"""
    p = Path(raw_png)
    return p.with_name(p.stem + "_top.png")


def legend_rects(t):
    """(x, y, w, h) of the legend panels drawn in composite()"""
    h0 = 28 + 26 * len(LEGEND)
    rects = [(14, 14, 142, h0)]
    if t >= 31:
        rects.append((14, 14 + h0 + 10, 218, 100))
    return rects


def overlap(a, b, pad=4):
    """overlap (ox, oy) of two (x, y, w, h) boxes, both > 0 when they intersect (with padding)"""
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) + pad,
            min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) + pad)


def crossing(p1, p2, q1, q2):
    """True if segments p1-p2 and q1-q2 intersect"""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (orient(p1, p2, q1) * orient(p1, p2, q2) < 0) and (orient(q1, q2, p1) * orient(q1, q2, p2) < 0)


def layout_labels(boxes, obstacles, ymax, anchors=None, iters=300):
    """in place: separate label boxes from each other and from fixed obstacles, inside [8, W-8] x [8, ymax];
    with anchors, label pairs whose leader lines cross swap places first"""
    if anchors:
        for _ in range(3):
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    bi, bj = boxes[i], boxes[j]
                    ci = (bi[0] + bi[2] / 2, bi[1] + bi[3] / 2)
                    cj = (bj[0] + bj[2] / 2, bj[1] + bj[3] / 2)
                    if crossing(anchors[i], ci, anchors[j], cj):
                        bi[0], bi[1] = cj[0] - bi[2] / 2, cj[1] - bi[3] / 2
                        bj[0], bj[1] = ci[0] - bj[2] / 2, ci[1] - bj[3] / 2
    def clamp(b):
        b[0] = min(max(b[0], 8), W - b[2] - 8)
        b[1] = min(max(b[1], 8), ymax - b[3])
    for b in boxes:
        clamp(b)
    for _ in range(iters):
        moved = False
        for i in range(len(boxes)):
            bi = boxes[i]
            for ob in obstacles:                      # obstacles do not move: push the label out entirely
                ox, oy = overlap(bi, ob)
                if ox > 0 and oy > 0:
                    moved = True
                    if oy < ox:
                        bi[1] += oy if bi[1] + bi[3] / 2 >= ob[1] + ob[3] / 2 else -oy
                    else:
                        bi[0] += ox if bi[0] + bi[2] / 2 >= ob[0] + ob[2] / 2 else -ox
            for j in range(i + 1, len(boxes)):
                bj = boxes[j]
                ox, oy = overlap(bi, bj)
                if ox > 0 and oy > 0:
                    moved = True
                    if oy < ox:
                        sgn = 1 if bi[1] <= bj[1] else -1
                        bi[1] -= sgn * oy / 2
                        bj[1] += sgn * oy / 2
                    else:
                        sgn = 1 if bi[0] <= bj[0] else -1
                        bi[0] -= sgn * ox / 2
                        bj[0] += sgn * ox / 2
            clamp(bi)
        for b in boxes:
            clamp(b)
        if not moved:
            break


def composite(scene, s, raw_png, out_png):
    from PIL import Image, ImageDraw
    F = fonts()
    im = background().copy()
    fg = Image.open(raw_png).convert("RGBA")
    im.alpha_composite(fg)
    top = top_path(raw_png)
    if top.exists():
        tp = Image.open(top).convert("RGBA")
        tp.putalpha(tp.getchannel("A").point(lambda v: int(v * TOP_ALPHA)))
        im.alpha_composite(tp)
    cam = s["cam"]
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    # usable area for labels: above the caption bar / closing card, right of the legend
    caps = [] if s["clean"] else caption_text(s["t"])
    bar_a = 0.0 if s["clean"] else bar_alpha(s["t"])
    bottom = H - BAR_H if bar_a > 0 else H
    if s["closing"] > 0:
        bottom = min(bottom, H - CLOSE_H)
    ymax = bottom - LABEL_GAP
    obstacles = []
    if s["legend"] > 0:
        obstacles.extend(legend_rects(s["t"]))

    # ring around the ligand in the opening shot, name in a box off to the side with a leader line
    if s["circle"] > 0:
        cx, cy = cam.project(scene.lig_c)
        r = 34 + 4 * math.sin(s["t"] * 3)
        a = int(255 * s["circle"])
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, a), width=4)
        d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], outline=(40, 50, 70, int(a * 0.5)), width=1)
        txt = "quercitrina"
        bw = d.textlength(txt, font=F["lab"]) + 16
        bx, by = cx + r + 70, cy + r + 40
        ex, ey = cx + r * 0.707, cy + r * 0.707
        d.line([(ex, ey), (bx, by + 14)], fill=(30, 45, 60, a), width=2)
        d.rounded_rectangle([bx, by, bx + bw, by + 28], radius=7, fill=(255, 255, 255, int(235 * s["circle"])),
                            outline=(35, 110, 125, a), width=2)
        d.text((bx + 8, by + 2), txt, font=F["lab"], fill=(15, 25, 35, a))

    # H-bond value label (placed first: residue labels avoid it)
    if s["hb_label"] > 0:
        hx, hy = cam.project(scene.pts["hb"])
        txt = "3,05 Å · 170°"
        wtxt = d.textlength(txt, font=F["hb"]) + 18
        al = int(255 * s["hb_label"])
        bx = min(max(hx + 70, 8), W - wtxt - 8)          # to the right, clear of the dash itself
        by = min(max(hy - 15, 8), ymax - 30)
        d.line([(hx, hy), (bx, by + 15)], fill=(120, 95, 0, al), width=2)
        d.rounded_rectangle([bx, by, bx + wtxt, by + 30], radius=8, fill=(255, 244, 170, int(245 * s["hb_label"])),
                            outline=(170, 130, 0, al), width=2)
        d.text((bx + 9, by + 2), txt, font=F["hb"], fill=(60, 45, 0, al))
        obstacles.append((bx, by, wtxt, 30))
        (px, py), (qx, qy) = (cam.project(scene.lig_xyz(LIG_O_HB)),
                              cam.project(scene.res_xyz(HB_RES, [scene.hb_acc])[0]))
        obstacles.append((min(px, qx) - 8, min(py, qy) - 8, abs(px - qx) + 16, abs(py - qy) + 16))  # the dash

    # boxed residue labels with leader lines
    items = []
    for r, a in s["labels"].items():
        if a <= 0:
            continue
        pts = scene.res_xyz(r, None, "sites")
        anchor = pts.mean(0) if len(pts) else scene.lig_c
        ax, ay = cam.project(anchor)
        items.append([r, a, ax, ay])
    if items:
        cxl, cyl = cam.project(scene.lig_c)
        boxes = []
        for r, a, ax, ay in items:
            vx, vy = ax - cxl, ay - cyl
            n = math.hypot(vx, vy) or 1.0
            wtxt = d.textlength(RESNAME[r], font=F["lab"]) + 16
            if ay + vy / n * 62 + 14 > ymax:              # no room below: put the label beside the residue
                side = 1 if vx >= 0 else -1
                boxes.append([ax + 40 if side > 0 else ax - 40 - wtxt, ay - 14, wtxt, 28])
            else:
                boxes.append([ax + vx / n * 62 - wtxt / 2, ay + vy / n * 62 - 14, wtxt, 28])
        lp = np.array([cam.project(p) for p in scene.lig])          # labels must not cover the ligand
        x0, y0 = lp.min(0) - 6
        x1, y1 = lp.max(0) + 6
        layout_labels(boxes, obstacles + [(x0, y0, x1 - x0, y1 - y0)], ymax, [(i[2], i[3]) for i in items])
        for (r, a, ax, ay), (bx, by, bw, bh) in zip(items, boxes):
            al = int(255 * a)
            ex = min(max(ax, bx), bx + bw)
            ey = min(max(ay, by), by + bh)
            d.line([(ax, ay), (ex, ey)], fill=(30, 45, 60, al), width=2)
            d.ellipse([ax - 3, ay - 3, ax + 3, ay + 3], fill=(30, 45, 60, al))
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=7, fill=(255, 255, 255, int(235 * a)),
                                outline=(35, 110, 125, al), width=2)
            d.text((bx + 8, by + 2), RESNAME[r], font=F["lab"], fill=(15, 25, 35, al))

    # legend
    if s["legend"] > 0:
        al = int(255 * s["legend"])
        d.rounded_rectangle([14, 14, 156, 14 + 28 + 26 * len(LEGEND)], radius=10, fill=(255, 255, 255, int(170 * s["legend"])))
        d.text((26, 20), "Superfície", font=F["lab"], fill=(25, 35, 50, al))
        for i, (txt, key) in enumerate(LEGEND):
            y = 52 + 26 * i
            c = tuple(int(255 * v) for v in TYPE_COLORS[key])
            d.rounded_rectangle([26, y, 46, y + 18], radius=4, fill=c + (al,), outline=(60, 60, 60, al), width=1)
            d.text((54, y - 3), txt, font=F["leg"], fill=(25, 35, 50, al))
        if s["t"] >= 31:
            y0 = 14 + 28 + 26 * len(LEGEND) + 10
            d.rounded_rectangle([14, y0, 232, y0 + 100], radius=10, fill=(255, 255, 255, int(170 * s["legend"])))
            for i, (txt, col) in enumerate([("contato hidrofóbico", (70, 70, 70)), ("empilhamento π", (205, 0, 205)),
                                            ("ligação de H", (225, 190, 0))]):
                y = y0 + 12 + 28 * i
                for k in range(4):
                    d.line([(26 + k * 11, y + 10), (26 + k * 11 + 7, y + 10)], fill=col + (al,), width=4)
                d.text((78, y - 1), txt, font=F["leg"], fill=(25, 35, 50, al))
    im.alpha_composite(ov)

    # caption bar
    bar = Image.new("RGBA", (W, BAR_H), (18, 28, 44, int(222 * bar_a)))
    layer = Image.new("RGBA", (W, BAR_H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for text, a in caps:
        lines = wrap(ld, text, F["cap"], W - 90)
        y = (BAR_H - 32 * len(lines)) // 2
        tl = Image.new("RGBA", (W, BAR_H), (0, 0, 0, 0))
        td = ImageDraw.Draw(tl)
        for ln in lines:
            td.text((45, y), ln, font=F["cap"], fill=(255, 255, 255, int(255 * min(1.0, a))))
            y += 34
        layer.alpha_composite(tl)
    bar.alpha_composite(layer)
    if bar_a > 0:
        im.alpha_composite(bar, (0, H - BAR_H))

    # title card (first seconds) and closing card
    if s["title"] > 0:
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        a = s["title"]
        cd.rounded_rectangle([0, 0, W, 190], radius=0, fill=(14, 24, 40, int(215 * a)))
        cd.text((50, 28), "Quercitrina na acetilcolinesterase humana", font=F["title"], fill=(255, 255, 255, int(255 * a)))
        cd.text((52, 108), "Hipótese de ligação por docking molecular · AChE (PDB 4EY6)", font=F["sub"],
                fill=(205, 220, 235, int(255 * a)))
        cd.text((52, 146), "Animação didática: sítios da garganta e contatos previstos", font=F["cap_small"],
                fill=(160, 185, 210, int(255 * a)))
        im.alpha_composite(card)
    if s["closing"] > 0:
        a = s["closing"]
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        y0 = H - CLOSE_H                              # low, semi-transparent card: the contacts stay visible above it
        cd.rectangle([0, y0, W, H], fill=(14, 24, 40, int(191 * a)))
        cd.text((50, y0 + 14), "Hipótese: ligação na garganta, do PAS ao CAS (dual-site)", font=F["title"].font_variant(size=38),
                fill=(255, 255, 255, int(255 * a)))
        cd.text((52, y0 + 72), "CNNscore 0,488 · CNNaffinity 6,43 pK · Vina −9,28 kcal/mol · 22/30 poses no sítio · PoseBusters aprovado",
                font=F["cap_small"], fill=(215, 228, 240, int(255 * a)))
        cd.text((52, y0 + 106), "Previsões computacionais: sugerem uma hipótese, não medem afinidade experimental.",
                font=F["cap_small"], fill=(175, 198, 220, int(255 * a)))
        im.alpha_composite(card)
    im.convert("RGB").save(out_png)


# ---- commands -------------------------------------------------------------------------------------
KEY_TIMES = [2.0, 8.5, 14.5, 25.0, 35.5, 43.0]


def cmd_render(a):
    import pymol
    from pymol import cmd
    if a.gl:                                              # already inside a PyMOL session with a window
        cmd.viewport(W, H)
        if tuple(cmd.get_viewport()) != (W, H):
            sys.exit(f"GL viewport is {cmd.get_viewport()}, expected {(W, H)}: start PyMOL with -W {W} -H {H}")
    else:
        pymol.finish_launching(["pymol", "-qc"])
    work = Path(a.work)
    (work / "frames").mkdir(parents=True, exist_ok=True)
    (work / "raw").mkdir(exist_ok=True)
    sc = Scene(str(Path(a.receptor).resolve()), str(Path(a.pose).resolve()), gl=a.gl, clean=a.clean)
    if a.gl:
        cmd.set("antialias_shader", 2)                    # SMAA
        sc.gl_background()
    print(f"H-bond: O19 -> Thr83 {sc.hb_acc} {sc.hb_dist:.2f} A, D-H...A {sc.hb_angle:.1f} deg "
          f"(ProLIF {HB_REF[0]:.2f} A, {HB_REF[1]:.1f} deg)", flush=True)
    if abs(sc.hb_dist - HB_REF[0]) > 0.05 or abs(sc.hb_angle - HB_REF[1]) > 1.0:
        sys.exit("H-bond geometry differs from ProLIF (the on-screen label would be wrong)")
    for r, ref in PI_REF.items():                         # magenta dashes: ring C centroid -> Tyr ring centroid
        dd = float(np.linalg.norm(sc.ringc - sc.ring_centroid(r)))
        print(f"pi: ring C -> {RESNAME[r]} ring centroid {dd:.2f} A (ProLIF {ref:.2f})", flush=True)
        if abs(dd - ref) > 0.05:
            sys.exit(f"pi-stacking distance to {RESNAME[r]} differs from ProLIF by more than 0.05 A")
    if a.keys:
        times = [(f"key{i}", t) for i, t in enumerate(KEY_TIMES)] if not a.times else \
            [(f"key{i}", float(x)) for i, x in enumerate(a.times.split(","))]
        for name, t in times:
            s = sc.state(t)
            raw = work / "raw" / f"{name}.png"
            t0 = time.time()
            sc.render(s, raw)
            composite(sc, s, raw, work / "frames" / f"{name}.png")
            print(f"{name} t={t} {time.time() - t0:.1f}s", flush=True)
        if not a.times:
            sheet(work)
        return
    n = int(DURATION * FPS)
    i0, i1 = (int(x) for x in a.frames.split(":")) if a.frames else (0, n)
    step = a.step
    t00 = time.time()
    for i in range(i0, min(i1, n), step):
        out = work / "frames" / f"f_{i:04d}.png"
        if out.exists() and not a.force:
            continue
        s = sc.state(i / FPS)
        raw = work / "raw" / f"r_{i:04d}.png"
        sc.render(s, raw)
        composite(sc, s, raw, out)
        raw.unlink(missing_ok=True)
        top_path(raw).unlink(missing_ok=True)
        if (i - i0) % 15 == 0:
            print(f"frame {i} ({time.time() - t00:.0f}s)", flush=True)


def sheet(work):
    from PIL import Image
    ims = [Image.open(work / "frames" / f"key{i}.png") for i in range(len(KEY_TIMES))]
    w, h = 640, 360
    out = Image.new("RGB", (w * 2 + 30, h * 3 + 40), (245, 245, 245))
    for k, im in enumerate(ims):
        out.paste(im.resize((w, h), Image.LANCZOS), (10 + (k % 2) * (w + 10), 10 + (k // 2) * (h + 10)))
    out.save(work.resolve().parent / "quadros_chave.png")


def cmd_encode(a):
    ff = a.ffmpeg or os.environ.get("FFMPEG") or "ffmpeg"
    work, out = Path(a.work), Path(a.out)
    src = str(work / "frames" / "f_%04d.png")
    missing = [i for i in range(int(DURATION * FPS)) if not (work / "frames" / f"f_{i:04d}.png").exists()]
    if missing:
        sys.exit(f"{len(missing)} frames missing (first: {missing[0]}); render them before encoding")
    mp4 = out / f"animacao_ache_quercitrina{a.suffix}.mp4"
    gif = out / f"animacao_ache_quercitrina{a.suffix}.gif"
    avif = out / f"animacao_ache_quercitrina{a.suffix}.avif"
    subprocess.run([ff, "-y", "-framerate", str(FPS), "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-preset", "slow", "-movflags", "+faststart", str(mp4)], check=True)
    pal = work / "palette.png"
    vf = "fps=%d,scale=%d:-1:flags=lanczos" % (a.gif_fps, a.gif_width)
    # GIF preview kept under ~8 MB: the camera moves in every frame, so few colours and no dithering
    subprocess.run([ff, "-y", "-i", str(mp4), "-vf", vf + f",palettegen=max_colors={a.gif_colors}:stats_mode=diff", str(pal)],
                   check=True)
    subprocess.run([ff, "-y", "-i", str(mp4), "-i", str(pal), "-lavfi",
                    vf + "[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle", str(gif)], check=True)
    # README preview: animated AVIF keeps full resolution in a few MB (the GIF is only the fallback)
    subprocess.run([ff, "-y", "-i", str(mp4), "-vf", "format=yuv420p", "-c:v", "libsvtav1", "-crf", str(a.avif_crf),
                    "-preset", "6", "-g", "300", "-an", "-f", "avif", str(avif)], check=True)
    for f in (mp4, gif, avif):
        print(f, f.stat().st_size)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="c", required=True)
    r = sub.add_parser("render")
    r.add_argument("--receptor", required=True)
    r.add_argument("--pose", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--keys", action="store_true")
    r.add_argument("--times", default="")
    r.add_argument("--frames", default="")
    r.add_argument("--step", type=int, default=1)
    r.add_argument("--force", action="store_true")
    r.add_argument("--gl", action="store_true", help="OpenGL rendering (run inside PyMOL with a window)")
    r.add_argument("--clean", action="store_true", help="no caption bar, title or closing card (README preview)")
    e = sub.add_parser("encode")
    e.add_argument("--work", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--ffmpeg", default="")
    e.add_argument("--gif-fps", type=int, default=10)
    e.add_argument("--gif-width", type=int, default=480)
    e.add_argument("--gif-colors", type=int, default=64)
    e.add_argument("--avif-crf", type=int, default=38)
    e.add_argument("--suffix", default="", help="file name suffix, e.g. _limpa for frames rendered with --clean")
    a = ap.parse_args()
    try:
        {"render": cmd_render, "encode": cmd_encode}[a.c](a)
    finally:                                              # also on errors: never leave a PyMOL window open
        if a.c == "render":
            from pymol import cmd
            cmd.quit()


if __name__ in ("__main__", "pymol"):                  # "pymol": run as a script by a PyMOL session
    main()
