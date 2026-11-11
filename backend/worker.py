"""Background worker: runs anomaly detection for every environment on a schedule.

Run from the backend folder:  python worker.py
"""

import logging
import os
import time

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Environment, Service
from app.services.detection import run_detection

INTERVAL = int(os.getenv("DETECTION_INTERVAL_SECONDS", "30"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    logging.info("Detection worker started (every %ss)", INTERVAL)
    while True:
        with SessionLocal() as db:
            envs = db.scalars(
                select(Environment).where(
                    Environment.services.any(Service.is_active.is_(True))
                )
            ).all()
            for env in envs:
                try:
                    report = run_detection(db, env)
                    logging.info(
                        "env %s: %s incident(s) touched, %s",
                        env.id,
                        len(report.incident_ids),
                        {r.service: r.outcome for r in report.results},
                    )
                except Exception:
                    db.rollback()
                    logging.exception("Detection failed for environment %s", env.id)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()