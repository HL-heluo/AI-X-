"""Run local-chain synchronization independently from generation and from each other."""

import logging
from collections.abc import Callable
from threading import Event, Thread

from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_session_factory
from app.services import chain_credits, evidence, work_trade_sync

logger = logging.getLogger("aivideo.chain")


def start_background(settings: Settings) -> Event:
    stop = Event()
    sync_jobs = []
    if settings.chain_enabled:
        sync_jobs.append(("vcr", chain_credits.execute_pending))
    if settings.fabric_enabled:
        sync_jobs.append(("fabric", evidence.execute_pending))
        sync_jobs.append(("fabric-trades", work_trade_sync.execute_pending))
    for name, sync in sync_jobs:
        Thread(target=_run, args=(stop, name, sync), name=f"aivideo-{name}", daemon=True).start()
    return stop


def _run(stop: Event, name: str, sync: Callable[[Session], object]) -> None:
    factory = get_session_factory()
    while not stop.is_set():
        try:
            with factory() as session:
                sync(session)
        except Exception as exc:
            logger.error("%s sync round failed (%s)", name, type(exc).__name__)
        stop.wait(2)
