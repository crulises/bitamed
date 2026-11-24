"""Application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import routes as auth_routes
from app.auth.sessions import get_redis
from app.config import settings
from app.db import engine
from app.logbooks import routes as logbook_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_redis()
    yield
    await engine.dispose()
    await get_redis().aclose()


app = FastAPI(
    title="bitamed",
    lifespan=lifespan,
    # No public API docs in production: the route list is a map of the system.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

app.include_router(auth_routes.router)
app.include_router(logbook_routes.router)
app.include_router(logbook_routes.invitations_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)

    # Shared views must never leak the token through the Referer header when
    # the doctor clicks an outbound link, and must never be indexed.
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path.startswith("/s/"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"

    if settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Never let a stack trace or a database error message reach the client:
    # they leak schema details, and here the schema describes medical records.
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocurrió un error inesperado."},
    )


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}
