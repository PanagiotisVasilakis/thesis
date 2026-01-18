# services/nef-emulator/backend/app/app/main.py

import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from app.core.config import settings
from app.api.api_v1.api import api_router, nef_router
from app.monitoring import metrics

# Where are we on disk?
BASE_DIR = Path(__file__).resolve().parent  # .../app/app
STATIC_DIR = BASE_DIR / "static"

# ================================= Main Application - NEF Emulator =================================

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# CORS - Allow Kinisis UI to connect
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(orig) for orig in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Internal NEF-emulator APIs
app.include_router(api_router, prefix=settings.API_V1_STR)

# ================================= Sub-Application - Northbound APIs =================================

nef_app = FastAPI(title="Northbound NEF APIs", openapi_url=None)
nef_app.include_router(nef_router, prefix=settings.API_V1_STR)
app.mount("/nef", nef_app)

@app.get("/metrics")
async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics."""
    return Response(
        generate_latest(metrics.REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )

# ================================= Middleware =================================

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    resp = await call_next(request)
    duration = time.time() - start
    resp.headers["X-Process-Time"] = str(duration)
    metrics.REQUEST_DURATION.labels(request.method, request.url.path).observe(duration)
    return resp

# ================================= Static Files =================================

# serve static assets at /static (scenarios, logos, docs)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ================================= Health Check =================================

@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "healthy", "service": "nef-emulator"}

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "NEF Emulator API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "ui": "Use Kinisis UI (separate frontend)"
    }
