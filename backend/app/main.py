import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, scheduler
from .db import SessionLocal
from .routers import (
    accounts,
    budget,
    categories,
    category_budgets,
    data,
    goals,
    income,
    investments,
    networth,
    overview,
    recurring,
    rsu,
    rules,
    sync,
    transactions,
)

logging.basicConfig(level=logging.INFO)


def _mark_interrupted() -> None:
    with SessionLocal() as db:
        if n := scheduler.mark_interrupted_runs(db):
            logging.getLogger("monarch-lite").warning("marked %d interrupted sync run(s) as failed", n)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(_mark_interrupted)
    task = asyncio.create_task(scheduler.loop())
    yield
    task.cancel()


app = FastAPI(title="monarch-lite", lifespan=lifespan)
# Blocks DNS rebinding: a hostile page can resolve its own name to 127.0.0.1, but its Host header stays foreign.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
for module in (accounts, sync, transactions, categories, rules, data, overview, budget, category_budgets, recurring, goals, investments, networth, rsu, income):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Mounted last so /api routes win. HashRouter on the frontend means no SPA fallback is needed.
if config.FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
