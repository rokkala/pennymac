"""Long-running processing worker (ECS Fargate 'worker' task, or `python -m lbp.worker` locally).

Claims queued batches and runs them through the micro-batch pipeline. Multiple workers can
run side by side: the claim is an atomic status update (queued -> running). Sequenced change files
that must wait for an earlier file go to 'waiting' and are requeued when that file completes.
With LBP_SCHEDULER_ENABLED the worker also runs the delivery-scheduler tick every minute.
"""
from __future__ import annotations

import logging
import signal
import time

from sqlalchemy import select

from .pipeline.batch import BatchBusyError, recover_stale, run_batch
from .rules.registry import RuleRegistry
from .store import db

log = logging.getLogger("lbp.worker")
_stop = False


def _sigterm(*_):
    global _stop
    _stop = True


def claim_next() -> str | None:
    with db.get_engine().begin() as c:
        row = c.execute(select(db.batches.c.batch_id).where(db.batches.c.status == "queued").order_by(db.batches.c.created_at).limit(1)).first()
        if not row:
            return None
        res = c.execute(db.batches.update().where(db.batches.c.batch_id == row[0], db.batches.c.status == "queued").values(status="claimed"))
        return row[0] if res.rowcount == 1 else None


def main(poll_seconds: float = 5.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _sigterm)
    RuleRegistry().seed_defaults()
    log.info("worker started")
    from .config import get_settings
    from .scheduling.service import tick

    last_sweep = 0.0
    while not _stop:
        if time.monotonic() - last_sweep > 60:
            for bid in recover_stale():
                log.warning("requeued stale batch %s", bid)
            if get_settings().scheduler_enabled:  # AWS: EventBridge Scheduler drives the tick instead
                try:
                    res = tick()
                    if res.get("late") or res.get("missed") or res.get("batches"):
                        log.info("scheduler: %s", {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()})
                except Exception:  # noqa: BLE001
                    log.exception("scheduler tick failed")
            last_sweep = time.monotonic()
        bid = claim_next()
        if not bid:
            time.sleep(poll_seconds)
            continue
        log.info("running batch %s", bid)
        try:
            log.info("batch %s done: %s", bid, run_batch(bid))
        except BatchBusyError:
            log.info("batch %s taken by another worker", bid)
        except Exception:  # noqa: BLE001
            log.exception("batch %s failed", bid)


if __name__ == "__main__":
    main()
