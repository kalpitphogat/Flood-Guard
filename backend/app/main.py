"""FloodGuard India — FastAPI application entry point.

Run locally:
    cd backend && uvicorn app.main:app --reload --port 8000

OpenAPI docs at http://localhost:8000/docs. The frontend's TypeScript types are
generated from this schema, so the Pydantic models are the single contract.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import catalog, health, monitoring, results, simulate, uploads, views
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.floodguard_log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Dam-break / flash-flood hydrodynamic simulation and inundation mapping.\n\n"
        "Smart India Hackathon PS 26161. Every number returned by this API is computed "
        "from input data on disk; nothing is hardcoded. Engine identity is reported "
        "truthfully by GET /api/health/engines."
    ),
)

# The Vite dev server runs on 5173; the production build is served by the same
# origin, so this list exists only for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(simulate.router)
app.include_router(results.router)
app.include_router(monitoring.router)
app.include_router(uploads.router)
app.include_router(views.router)


@app.on_event("startup")
def _start_job_runner() -> None:
    """Bring the job runner up with the app, and mark any orphaned jobs.

    A job recorded as running when the process died did not survive it, and
    leaving it as 'running' would have the UI wait forever.
    """
    simulate.get_runner()


@app.on_event("shutdown")
def _stop_job_runner() -> None:
    simulate.get_runner().stop()


# --- the built dashboard -----------------------------------------------------------
#
# When `npm run build` has produced frontend/dist, the API serves it too, so the
# whole system runs as ONE process on ONE port — no Vite dev server, no proxy,
# nothing else to start at a venue. Client-side routes (/simulation, /s/<code>)
# fall back to index.html; /api, /ws and /docs are never shadowed.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if (FRONTEND_DIST / "index.html").exists():
    app.mount(
        "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"
    )

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "ws/", "docs", "openapi.json", "redoc")):
            raise HTTPException(status_code=404)
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.version,
            "docs": "/docs",
            "health": "/health",
            "dashboard": "not built — run `cd frontend && npm run build`, or use the Vite "
                         "dev server on :5173",
        }
