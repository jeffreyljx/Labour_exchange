from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine
import app.models  # noqa: F401 - register SQLAlchemy models before create_all
from app.models.base import Base
from app.routers import admin_panel, auth, contracts, orders, portfolio, profile, reputation, settlement, trades, websocket_live_feed

app = FastAPI(
    title="Human Capital Exchange",
    description="An order book exchange for trading fractional income-share contracts.",
    version="0.1.0",
)

# Origins are configured via CORS_ORIGINS env var (JSON list or comma-separated).
# allow_origins=["*"] + allow_credentials=True is a CORS spec violation and rejected
# by browsers — explicit origins are required when credentials are included.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin_panel.router)
app.include_router(profile.router)
app.include_router(contracts.router)
app.include_router(orders.router)
app.include_router(trades.router)
app.include_router(portfolio.router)
app.include_router(settlement.router)
app.include_router(reputation.router)
app.include_router(websocket_live_feed.router)


@app.on_event("startup")
def create_dev_tables():
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)


@app.get("/health")
@app.get("/healthz")
def health():
    return {"status": "ok"}
