"""Background analysis worker.

**Not required.** Analyses run synchronously today and finish in a few seconds.
This exists for when that stops being true, and it is written now so that adding
it later is configuration rather than a redesign.

The separation it relies on already exists in the application:

* `services.analysis_service.run_assessment()` takes an explicit ``Session`` and
  commits its own work, so it runs unchanged inside a worker loop.
* ``analyses.status`` (``pending``/``running``/``complete``/``failed``) and
  ``analysis_service.progress_for()`` already model an in-flight run.
* ``GET /analyses/{id}/progress`` reads that state, so the interface needs no
  change at all.

Run it with::

    python -m workers.analysis_worker --poll-interval 2 --batch-size 5

The claim below is exactly what makes this safe to add late rather than
prematurely: because no agent performs a calculation, dropping the agent step
here would slow a run down but would not change a single figure in the result.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.analysis import Analysis  # noqa: E402
from app.models.well import Well  # noqa: E402
from app.services import analysis_service  # noqa: E402

logger = logging.getLogger("workers.analysis")


class Worker:
    """Claims queued analyses and runs them.

    Claiming is an ``UPDATE ... WHERE status = 'pending'`` rather than a
    ``SELECT`` followed by an update. With more than one worker, select-then-update
    hands the same row to every worker in turn, and two analyses of the same well
    race each other into the database. The conditional update is what makes the
    claim atomic.
    """

    def __init__(self, *, batch_size: int = 5, include_agents: bool = True) -> None:
        self.batch_size = batch_size
        self.include_agents = include_agents
        self._stop = False

    def request_stop(self, *_args: object) -> None:
        """Finish the current analysis, then stop.

        Signal handling is cooperative rather than immediate: killing the process
        mid-run leaves a row in ``running`` with no owner, and a row nobody owns
        is worse than a row that finishes thirty seconds late.
        """
        logger.info("stop requested; finishing the current batch")
        self._stop = True

    def claim(self, db: Session) -> list[uuid.UUID]:
        """Atomically move up to ``batch_size`` pending rows to running."""
        pending = list(
            db.scalars(
                select(Analysis.id)
                .where(Analysis.status == "pending")
                .order_by(Analysis.created_at)
                .limit(self.batch_size)
            )
        )
        if not pending:
            return []

        ids = [analysis_id for analysis_id in pending if analysis_id is not None]
        if not ids:
            return []

        result = db.execute(
            update(Analysis)
            .where(Analysis.id.in_(ids), Analysis.status == "pending")
            .values(status="running")
        )
        db.commit()

        # `rowcount` can be lower than `ids` if another worker won the race.
        # Only the rows this worker actually claimed may be run.
        claimed = result.rowcount or 0
        if claimed < len(ids):
            logger.info("claimed %d of %d pending analyses", claimed, len(ids))
        return ids[:claimed]

    def process(self, db: Session, analysis_id: uuid.UUID) -> None:
        analysis = db.get(Analysis, analysis_id)
        if analysis is None:
            logger.warning("analysis %s disappeared before it could run", analysis_id)
            return

        well = db.get(Well, analysis.well_id)
        if well is None:
            # A foreign key should make this impossible. If it happens, the row
            # is marked failed rather than left pending forever, because a
            # permanently queued row looks like a healthy queue and is not.
            analysis.status = "failed"
            analysis.error_message = f"well {analysis.well_id} no longer exists"
            db.commit()
            return

        logger.info("running %s for well %s", analysis_id, well.well_id)
        started = datetime.now(timezone.utc)

        try:
            # The analysis row already exists and already holds the parameters
            # and scenario, so this is a re-run of an existing request rather
            # than a new one. persist=False keeps the queue row authoritative
            # rather than creating a second analysis for the same request.
            _, assessment, _ = analysis_service.run_assessment(
                db,
                well,
                include_ai=self.include_agents,
                tenant_id=analysis.tenant_id,
                persist=False,
            )

            analysis.feasibility_score = assessment.feasibility_score
            analysis.confidence_score = assessment.confidence_score
            analysis.recommendation = assessment.recommendation
            # Text, not a list: the column is Text, and the rationale reads as
            # prose in the report and the UI.
            analysis.recommendation_rationale = "\n".join(
                assessment.recommendation_rationale
            )
            analysis.score_components = dict(assessment.component_scores)
            analysis.next_action = assessment.next_action
            analysis.recommended_configuration = assessment.configuration
            analysis.source_temperature_c = assessment.source_temperature_c
            analysis.temperature_status = assessment.temperature_status
            analysis.thermal_output_kw = assessment.thermal_output_kw
            analysis.thermal_output_status = assessment.thermal_output_status
            analysis.heat_pump_cop = assessment.heat_pump_cop
            analysis.delivered_heat_kw = assessment.delivered_heat_kw
            analysis.network_length_m = assessment.network_length_m
            analysis.network_heat_loss_kw = assessment.network_heat_loss_kw
            analysis.demand_matched_kw = assessment.demand_matched_kw
            analysis.nearest_building_distance_m = assessment.nearest_building_distance_m
            analysis.annual_heat_production_kwh = assessment.annual_heat_kwh
            analysis.capex_gbp = assessment.capex_gbp
            analysis.opex_gbp_per_year = assessment.opex_gbp_per_year
            analysis.lcoh_p_per_kwh = assessment.lcoh_p_per_kwh
            analysis.npv_gbp = assessment.npv_gbp
            analysis.irr_pct = assessment.irr_pct
            analysis.payback_years = assessment.payback_years
            analysis.break_even_heat_price_p_per_kwh = (
                assessment.break_even_heat_price_p_per_kwh
            )

            if assessment.risk_assessment is not None:
                analysis.risk_score = assessment.risk_assessment.aggregate_score
                analysis.risk_count = len(assessment.risk_assessment.risks)
                analysis.critical_risk_count = sum(
                    1 for risk in assessment.risk_assessment.risks if risk.is_critical
                )

            # `data_gaps` is a JSON column, so the gap list and the warning list
            # are stored under separate keys rather than collapsed. Merging them
            # would lose the distinction between "we could not measure this" and
            # "we measured it and it is worse than expected".
            analysis.data_gaps = {
                "gaps": list(assessment.data_gaps),
                "unknowns": list(assessment.unknowns),
                "warnings": list(assessment.warnings),
            }

            analysis.status = "complete"
            analysis.progress_stage = "final_assessment"
            analysis.started_at = analysis.started_at or started
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.duration_seconds = (
                analysis.completed_at - analysis.started_at
            ).total_seconds()
            analysis.error_message = None
            db.commit()

            logger.info(
                "completed %s: score=%.1f confidence=%.3f recommendation=%s",
                analysis_id,
                assessment.feasibility_score,
                assessment.confidence_score,
                assessment.recommendation,
            )

        except Exception as exc:  # noqa: BLE001 - one bad well must not stop the worker
            db.rollback()
            logger.exception("analysis %s failed", analysis_id)
            try:
                failed = db.get(Analysis, analysis_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.error_message = f"{type(exc).__name__}: {exc}"[:2000]
                    failed.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:  # noqa: BLE001 - the failure record is best-effort
                db.rollback()
                logger.exception("could not record the failure for %s", analysis_id)

    def run_once(self) -> int:
        """Process one batch. Returns how many were run."""
        with SessionLocal() as db:
            ids = self.claim(db)
            for analysis_id in ids:
                self.process(db, analysis_id)
        return len(ids)

    def run_forever(self, poll_interval: float) -> None:
        logger.info(
            "worker started: batch_size=%d poll_interval=%ss agents=%s",
            self.batch_size,
            poll_interval,
            self.include_agents,
        )
        while not self._stop:
            try:
                count = self.run_once()
            except Exception:  # noqa: BLE001 - a transient error must not kill the worker
                logger.exception("batch failed; retrying after the poll interval")
                count = 0

            if count == 0 and not self._stop:
                time.sleep(poll_interval)
        logger.info("worker stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workers.analysis_worker",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="Skip the agent interpretation. Results are numerically identical; "
        "only the narrative is missing.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single batch and exit. Useful for cron or a one-shot task.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    worker = Worker(batch_size=args.batch_size, include_agents=not args.no_agents)

    signal.signal(signal.SIGINT, worker.request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, worker.request_stop)

    if args.once:
        count = worker.run_once()
        print(f"processed {count} analyses")
        return 0

    worker.run_forever(args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())