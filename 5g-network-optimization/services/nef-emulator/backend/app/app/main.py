# services/nef-emulator/backend/app/app/main.py

import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from app.core.config import settings
from app.api.api_v1.api import api_router, nef_router
from app.monitoring import metrics

# Where are we on disk?
BASE_DIR = Path(__file__).resolve().parent  # .../app/app
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "ui"

# ================================= Main Application - NEF Emulator =================================

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# CORS
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

# ================================= Static Files & Templates =================================

# serve static assets at /static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# configure Jinja2 templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ================================= UI Routes =================================

@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    return RedirectResponse("/dashboard")

@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/map", response_class=HTMLResponse)
async def map_view(request: Request):
    return templates.TemplateResponse("map.html", {"request": request})

@app.get("/export", response_class=HTMLResponse)
async def export(request: Request):
    return templates.TemplateResponse("export.html", {"request": request})

@app.get("/import", response_class=HTMLResponse)
async def import_view(request: Request):
    return templates.TemplateResponse("import.html", {"request": request})

@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})

@app.get("/err404", response_class=HTMLResponse)
async def err404(request: Request):
    return templates.TemplateResponse("404.html", {"request": request})

@app.get("/err401", response_class=HTMLResponse)
async def err401(request: Request):
    return templates.TemplateResponse("401.html", {"request": request})

@app.get("/err500", response_class=HTMLResponse)
async def err500(request: Request):
    return templates.TemplateResponse("500.html", {"request": request})
