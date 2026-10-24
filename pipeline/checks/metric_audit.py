"""Anti cherry-picking: show every score side by side, say whether the conclusion depends on the metric,
and whether the score spread is large enough to discriminate at all.

python metric_audit.py results_dir [--primary cnn_score] [--lead LIGAND] [--min-spread 1.0]
Writes <results>/metric_audit.md and prints it (compact). Exit 1 if the lead's position depends on the metric.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# metric -> higher is better?
METRICS = {"vina": False, "cnn_affinity": True, "cnn_score": True, "le_vina": True}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def ranks(rows: list[dict], metric: str) -> dict[str, int]:
    vals = [(r["ligand_id"], _f(r.get(metric))) for r in rows]
    vals = [(k, v) for k, v in vals if v is not None]
    vals.sort(key=lambda kv: kv[1], reverse=METRICS[metric])
    return {k: i + 1 for i, (k, _) in enumerate(vals)}


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    def rk(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos + 1.0
        return r
    ra, rb = rk(a), rk(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(cov / (va * vb), 3) if va and vb else None


def audit(rows: list[dict], primary: str, lead: str | None, min_spread: float, exclude: str = "_controle") -> tuple[str, bool]:
    series = [r for r in rows if r.get("status", "ok") == "ok" and exclude not in r["ligand_id"]]
    for r in series:
        if not r.get("le_vina") and _f(r.get("vina")) is not None and _f(r.get("heavy_atoms")):
            r["le_vina"] = round(-_f(r["vina"]) / _f(r["heavy_atoms"]), 3)
    rk = {m: ranks(series, m) for m in METRICS}
    lines = [f"# Auditoria de métricas (métrica primária pré-registrada: `{primary}`)", "",
             "| ligante | " + " | ".join(f"{m} (pos.)" for m in METRICS) + " | d_sitio (Å) |",
             "|---|" + "---|" * (len(METRICS) + 1)]
    for r in sorted(series, key=lambda r: rk[primary].get(r["ligand_id"], 99)):
        cells = [f"{_f(r.get(m)):.3f} ({rk[m].get(r['ligand_id'], '-')})" if _f(r.get(m)) is not None else "-"
                 for m in METRICS]
        d = _f(r.get("site_distance_A"))
        lines.append(f"| {r['ligand_id']} | " + " | ".join(cells) + (f" | {d:.2f} |" if d is not None else " | - |"))
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
    lines.append(f"- Spearman ρ(CNNaffinity, −Vina) = {rho}")
    if lead:
        pos = {m: rk[m].get(lead) for m in METRICS}
        best_by = [m for m, p in pos.items() if p == 1]
        lines.append(f"- Posição de `{lead}` por métrica: {pos}")
        if best_by and len(best_by) < len(METRICS):
            warn = True
            lines.append(f"- ⚠ `{lead}` só é o melhor por {best_by}: a conclusão **depende da métrica**. "
                         f"Relate todas as métricas e use a primária pré-registrada (`{primary}`).")
        elif not best_by:
            lines.append(f"- `{lead}` não é o melhor em nenhuma métrica: não afirme superioridade energética.")
    lines.append("- Lembrete: escores ≠ afinidade experimental; diferenças < 1 kcal/mol estão dentro do erro do Vina.")
    return "\n".join(lines), warn


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("--primary", default="cnn_score", choices=list(METRICS))
    ap.add_argument("--lead", help="composto de interesse (ex.: o mais ativo experimentalmente)")
    ap.add_argument("--min-spread", type=float, default=1.0)
    a = ap.parse_args(argv)
    rows = list(csv.DictReader(open(Path(a.results) / "ranking.csv", encoding="utf-8")))
    text, warn = audit(rows, a.primary, a.lead, a.min_spread)
    (Path(a.results) / "metric_audit.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
