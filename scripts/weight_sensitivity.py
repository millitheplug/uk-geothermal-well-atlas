"""Weight sensitivity test for the feasibility scoring engine.

Re-runs the UNMODIFIED pipeline for every well that has a temperature record,
then recomputes each well's composite score under perturbed weight vectors and
asks:

  1. Does the ranking move?   (Spearman rho + pairwise order flips)
  2. Does a well's band move? (re-banded with the engine's own recommend())
  3. How far does any score move? (max/mean absolute delta)

The database is COPIED to a temporary directory first; nothing here touches the
application's data. The only thing replaced is the weight vector -- every
component score is the engine's own output, and the recomputed baseline is
asserted against the engine's stored feasibility score to 1e-6.

Usage:
    python scripts/weight_sensitivity.py [--db path/to/dev.db]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(REPO / "dev.db"),
        help="database to copy and assess (default: dev.db at the repo root)",
    )
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="weight_sensitivity_"))
    db_copy = workdir / "dev_sens.db"
    shutil.copy2(args.db, db_copy)

    os.environ["DATABASE_URL"] = f"sqlite:///{db_copy}"
    os.environ.setdefault("ENVIRONMENT", "development")
    sys.path.insert(0, str(BACKEND))

    from app.db.session import SessionLocal
    from app.engineering import scoring
    from app.engineering.pipeline import assess_well
    from app.models.well import Well
    from app.services import analysis_service as svc

    components = list(scoring.WEIGHTS.keys())
    baseline_weights = dict(scoring.WEIGHTS)

    def perturbed(component: str, delta: float) -> dict[str, float]:
        """Shift one weight by `delta` points, renormalising the others."""
        w = dict(baseline_weights)
        room = 1.0 - baseline_weights[component]
        new = min(max(baseline_weights[component] + delta, 0.0), 1.0)
        scale = (1.0 - new) / room
        for k in w:
            w[k] = new if k == component else baseline_weights[k] * scale
        return w

    scenarios: dict[str, dict[str, float]] = {"baseline": dict(baseline_weights)}
    for component in components:
        for delta in (-0.10, -0.05, 0.05, 0.10):
            if baseline_weights[component] + delta < 0:
                continue
            scenarios[f"{component}{delta:+.2f}"] = perturbed(component, delta)
    scenarios["equal weights (0.125 each)"] = {k: 1 / 8 for k in components}
    scenarios["confidence weight = 0"] = perturbed(
        "data_confidence", -baseline_weights["data_confidence"]
    )

    def band_for(score: float, rec: dict) -> str:
        recommendation, _ = scoring.recommend(
            feasibility_score=score,
            confidence_score=rec["confidence"],
            critical_risk_count=rec["critical_count"],
            critical_integrity_risk=rec["critical_integrity"],
        )
        return recommendation.value

    def spearman(xs: list[float], ys: list[float]) -> float:
        def ranks(vals: list[float]) -> list[float]:
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            r = [0.0] * len(vals)
            for position, idx in enumerate(order):
                r[idx] = position + 1
            return r

        rx, ry = ranks(xs), ranks(ys)
        n = len(xs)
        d2 = sum((a - b) ** 2 for a, b in zip(rx, ry, strict=False))
        return 1 - 6 * d2 / (n * (n * n - 1))

    # ---- run the engine once per well ------------------------------------
    db = SessionLocal()
    wells = (
        db.query(Well)
        .filter(Well.temperature_c.isnot(None))
        .order_by(Well.well_id)
        .all()
    )
    records = []
    for well in wells:
        inputs, _ = svc.build_well_inputs(db, well)
        assessment = assess_well(inputs)
        records.append(
            {
                "well_id": well.well_id,
                "name": well.well_name,
                "is_mock": str(well.source).startswith("mock_"),
                "components": {k: float(v) for k, v in assessment.component_scores.items()},
                "confidence": float(assessment.confidence_score),
                "critical_count": len(assessment.risk_assessment.critical_risks),
                "critical_integrity": any(
                    r.category == "well_integrity"
                    for r in assessment.risk_assessment.critical_risks
                ),
                "baseline_score": float(assessment.feasibility_score),
                "baseline_band": str(assessment.recommendation),
            }
        )
    db.close()

    # Sanity: recomputing the composite from the weights must reproduce the
    # engine, which also demonstrates the data_confidence term is live.
    for rec in records:
        recomputed = (
            sum(baseline_weights[k] * rec["components"][k] for k in components) * 100.0
        )
        assert abs(recomputed - rec["baseline_score"]) < 1e-6, (
            rec["well_id"],
            recomputed,
            rec["baseline_score"],
        )
    print(
        f"sanity check passed: composite recomputed from WEIGHTS matches the "
        f"engine for all {len(records)} wells\n"
    )

    baseline_scores = [r["baseline_score"] for r in records]
    baseline_bands = [r["baseline_band"] for r in records]
    well_id_is_mock = {r["well_id"]: r["is_mock"] for r in records}

    header = (
        f"{'scenario':<34} {'rho':>7} {'rho real':>8} {'flips':>6} {'band chg':>8} "
        f"{'max |d|':>8} {'mean |d|':>8}"
    )
    print(header)
    print("-" * len(header))

    real_idx = [i for i, r in enumerate(records) if not r["is_mock"]]
    changes: list[tuple[str, str, str, str]] = []
    for name, weights in scenarios.items():
        scores, bands = [], []
        for rec in records:
            s = sum(weights[k] * rec["components"][k] for k in components) * 100.0
            scores.append(s)
            bands.append(rec["baseline_band"] if name == "baseline" else band_for(s, rec))
        rho = spearman(baseline_scores, scores)
        rho_real = spearman(
            [baseline_scores[i] for i in real_idx], [scores[i] for i in real_idx]
        )
        flips = sum(
            1
            for i in range(len(scores))
            for j in range(i + 1, len(scores))
            if (baseline_scores[i] - baseline_scores[j]) * (scores[i] - scores[j]) < 0
        )
        deltas = [abs(a - b) for a, b in zip(scores, baseline_scores, strict=False)]
        changed = [
            (rec, ob, nb)
            for rec, ob, nb in zip(records, baseline_bands, bands, strict=False)
            if ob != nb
        ]
        print(
            f"{name:<34} {rho:>7.4f} {rho_real:>8.4f} {flips:>6} {len(changed):>8} "
            f"{max(deltas):>8.2f} {sum(deltas) / len(deltas):>8.2f}"
        )
        for rec, ob, nb in changed:
            changes.append((name, f"{rec['well_id']} {rec['name']}", ob, nb))

    print(
        f"\n(rho = Spearman rank correlation over all {len(records)} temperature "
        f"wells; rho real = the same computed on the {len(real_idx)} real NSTA "
        "wells only)"
    )

    print("\nBand changes (every scenario, every well; [synthetic] tagged):")
    if not changes:
        print("  none -- no well changes band under any +/-5 or +/-10 point shift")
    for name, well, ob, nb in changes:
        tag = "  [synthetic]" if well_id_is_mock.get(well.split(" ", 1)[0]) else ""
        print(f"  {name:<30} {well:<40} {ob} -> {nb}{tag}")

    print("\nBaseline picture (engine output, unchanged):")
    real = sum(1 for r in records if not r["is_mock"])
    print(f"  wells assessed: {len(records)} (real: {real}, synthetic: {len(records) - real})")
    bands: dict[str, int] = {}
    for rec in records:
        bands[rec["baseline_band"]] = bands.get(rec["baseline_band"], 0) + 1
    print(f"  bands: {bands}")
    for r in sorted(records, key=lambda r: -r["baseline_score"])[:5]:
        tag = "  [synthetic]" if r["is_mock"] else ""
        print(f"  {r['baseline_score']:>6.2f}  {r['baseline_band']:<15} "
              f"{r['well_id']} {r['name']}{tag}")

    print(f"\n(copy of the database used: {db_copy})")


if __name__ == "__main__":
    main()
