"""Anti cherry-picking: every score side by side, whether the lead's position depends on the metric, and
whether the score spread can discriminate at all. Pose selection is fixed by the pipeline (highest CNNscore
among PoseBusters-valid in-site poses); the pre-registered metric ranks LIGANDS.

python metric_audit.py results_dir [--primary cnn_score] [--lead ID] [--exclude ID,ID] [--min-spread 1.0]
Writes <results>/metric_audit.md. Exit 1 if the lead's position depends on the metric, 2 on invalid input.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

# ranking metrics -> higher is better?
METRICS = {"vina": False, "cnn_affinity": True, "cnn_score": True, "le_vina": True}
SHOWN = ["diffdock_confidence", "cnn_affinity_variance", "posebusters_pass", "n_poses_pb_pass", "site_distance_A"]


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def ranks(rows: list[dict], metric: str) -> dict[str, float]:
    """Average ranks for ties (1 = best)."""
    vals = sorted(((r["ligand_id"], _f(r.get(metric))) for r in rows if _f(r.get(metric)) is not None),
                  key=lambda kv: kv[1], reverse=METRICS[metric])
    out, i = {}, 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1][1] == vals[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[vals[k][0]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    def rk(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = rk(a), rk(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(cov / (va * vb), 3)


def audit(rows: list[dict], primary: str, lead: str | None, min_spread: float,
          exclude: set[str] | None = None) -> tuple[str, bool]:
    if primary not in METRICS:
        raise ValueError(f"métrica primária inválida: {primary} (use {list(METRICS)})")
    exclude = exclude or set()
    failed = [r["ligand_id"] for r in rows if r.get("status", "ok") != "ok"]
    series = [r for r in rows if r.get("status", "ok") == "ok" and r["ligand_id"] not in exclude]
    if lead and lead not in {r["ligand_id"] for r in series}:
        raise ValueError(f"composto líder '{lead}' não está na série ranqueada ({[r['ligand_id'] for r in series]})")
    for r in series:
        if _f(r.get("le_vina")) is None and _f(r.get("vina")) is not None and _f(r.get("heavy_atoms")):
            r["le_vina"] = round(-_f(r["vina"]) / _f(r["heavy_atoms"]), 3)
    rk = {m: ranks(series, m) for m in METRICS}
    head = [f"{m} (pos.)" for m in METRICS] + SHOWN
    lines = [f"# Auditoria de métricas (ranking de ligantes pela métrica pré-registrada `{primary}`)", "",
             "| ligante | " + " | ".join(head) + " |", "|---|" + "---|" * len(head)]
    for r in sorted(series, key=lambda r: rk[primary].get(r["ligand_id"], 99)):
        cells = [f"{_f(r.get(m)):.3f} ({rk[m][r['ligand_id']]:g})" if r["ligand_id"] in rk[m] else "—" for m in METRICS]
        cells += [str(r.get(c, "")) or "—" for c in SHOWN]
        lines.append(f"| {r['ligand_id']} | " + " | ".join(cells) + " |")
    if exclude:
        lines.append(f"\nControles fora do ranking da série: {', '.join(sorted(exclude))}")
    if failed:
        lines.append(f"\n- ⚠ Ligantes que falharam (relate no texto): {', '.join(failed)}")
    warn = False
    lines.append("")
    vina = [_f(r.get("vina")) for r in series if _f(r.get("vina")) is not None]
    if len(vina) >= 2:
        spread = max(vina) - min(vina)
        msg = f"- Amplitude do Vina na série: {spread:.2f} kcal/mol"
        if spread < min_spread:
            msg += f" (< {min_spread:g}): **os escores não discriminam a série**; não use o Vina como argumento de atividade."
        lines.append(msg)
    common = [r for r in series if _f(r.get("cnn_affinity")) is not None and _f(r.get("vina")) is not None]
    rho = spearman([_f(r["cnn_affinity"]) for r in common], [-_f(r["vina"]) for r in common])
    lines.append(f"- Spearman ρ(CNNaffinity, −Vina) = {rho if rho is not None else 'indefinido'}")
    if lead:
        pos = {m: rk[m].get(lead) for m in METRICS}
        lines.append(f"- Posição de `{lead}` por métrica: " + ", ".join(f"{m}={p:g}" for m, p in pos.items() if p))
        if len({p for p in pos.values() if p is not None}) > 1:
            warn = True
            lines.append(f"- ⚠ A posição de `{lead}` **depende da métrica**. Relate todas; a conclusão usa "
                         f"`{primary}` (pré-registrada), em que ele fica em {pos[primary]:g}º.")
        if pos[primary] and pos[primary] > 1:
            lines.append(f"- `{lead}` não é o melhor pela métrica pré-registrada: não afirme superioridade por escore.")
    lines.append("- Escores ≠ afinidade experimental; diferenças < 1 kcal/mol estão dentro do erro do Vina.")
    return "\n".join(lines), warn


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("--primary", default="cnn_score")
    ap.add_argument("--lead", help="composto de interesse (o mais ativo experimentalmente)")
    ap.add_argument("--exclude", default="", help="IDs de controles/cocristal, separados por vírgula")
    ap.add_argument("--min-spread", type=float, default=1.0)
    a = ap.parse_args(argv)
    f = Path(a.results) / "ranking.csv"
    if not f.exists():
        print(f"✗ {f} não existe")
        return 2
    rows = list(csv.DictReader(open(f, encoding="utf-8")))
    try:
        text, warn = audit(rows, a.primary, a.lead, a.min_spread, {x for x in a.exclude.split(",") if x})
    except ValueError as e:
        print("✗", e)
        return 2
    (Path(a.results) / "metric_audit.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
