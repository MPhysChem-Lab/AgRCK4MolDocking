"""Figure guards.

In a PyMOL render script:
    from checks.figure_check import require_objects, write_manifest
    require_objects(cmd, ["receptor", "lig_quercitrina", "lig_tacrina"])   # raises if any has 0 atoms
    cmd.png(out, ...); write_manifest(out, cmd, objects, note="...")

CLI:  python figure_check.py FIG_DIR      -> every PNG has a manifest entry with all objects non-empty
Also: a pymol build that stamps an evaluation watermark must NOT be used for figures, and the
watermark must never be cropped, masked or painted over. Use open-source PyMOL instead.
"""
from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path

OPEN_SOURCE_DISTS = ("pymol-open-source", "pymol-open-source-whl", "pymol_open_source")


def pymol_is_open_source() -> tuple[bool, str]:
    for d in OPEN_SOURCE_DISTS:
        try:
            return True, f"{d} {metadata.version(d)}"
        except metadata.PackageNotFoundError:
            pass
    try:
        import pymol  # noqa: F401
        from pymol import cmd
        v = cmd.get_version()[0]
    except Exception:
        return False, "PyMOL não importável"
    # conda-forge 'pymol-open-source' installs as conda package without pip metadata
    try:
        import pymol.licensing  # noqa: F401  (present only in Incentive/Schrodinger builds)
        return False, f"PyMOL {v} (build Incentive/Schrödinger: exige licença; não use para figuras)"
    except ImportError:
        return True, f"PyMOL {v} (open-source)"


def require_objects(cmd, names: list[str]) -> dict[str, int]:
    counts = {n: cmd.count_atoms(f"model {n}") if n in cmd.get_names("all") else 0 for n in names}
    empty = [n for n, c in counts.items() if c == 0]
    if empty:
        raise RuntimeError(f"objetos vazios/ausentes na cena: {empty} — a figura ficaria incompleta")
    return counts


def write_manifest(png: str | Path, cmd, objects: list[str], note: str = "") -> None:
    png = Path(png)
    man = png.parent / "figuras_manifest.json"
    data = json.loads(man.read_text(encoding="utf-8")) if man.exists() else {}
    ok, build = pymol_is_open_source()
    data[png.name] = {"objects": require_objects(cmd, objects), "pymol": build, "open_source": ok, "note": note}
    man.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = Path((argv or sys.argv[1:])[0])
    man = d / "figuras_manifest.json"
    errs = []
    data = json.loads(man.read_text(encoding="utf-8")) if man.exists() else {}
    for png in sorted(d.glob("*_3d*.png")) + sorted(d.glob("Fig*.png")):
        e = data.get(png.name)
        if e is None:
            errs.append(f"{png.name}: sem entrada no manifesto (render sem require_objects/write_manifest)")
        elif not e.get("open_source"):
            errs.append(f"{png.name}: renderizada com PyMOL não open-source ({e.get('pymol')})")
        elif any(c == 0 for c in e["objects"].values()):
            errs.append(f"{png.name}: objeto vazio {e['objects']}")
    if not data and not errs:
        errs.append(f"nenhuma figura renderizada em {d} (agrck figure ID spec.yaml)")
    for x in errs:
        print("✗", x)
    print("figure_check:", "OK" if not errs else f"{len(errs)} problema(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
