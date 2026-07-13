import uuid
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.logging import setup_logging, request_id_ctx
from app.core.exceptions import (
    AppError,
    app_error_handler,
    validation_exception_handler,
    global_exception_handler,
)
from app.api.health import router as health_router
from app.api.calls import router as calls_router

# Initialize logging immediately upon loading the module
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic (if required)
    yield
    # Shutdown logic (if required)

app = FastAPI(
    title="Call Analyzer API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None
)

# Request tracing middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_ctx.set(req_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

# CORS configuration
origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom exception handlers
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Register API routers
app.include_router(health_router, tags=["Health"])
app.include_router(calls_router, prefix="/api/v1", tags=["Calls"])

# ── Frontend SPA serving ───────────────────────────────────────────
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

_FRONTEND_DIR = os.path.normpath(_FRONTEND_DIR)

if os.path.isdir(_FRONTEND_DIR):
    _INDEX = os.path.join(_FRONTEND_DIR, "index.html")

    # Serve CSS, JS, and other assets from /static/
    app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")

    # Serve the SPA index.html for root and any non-API path
    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str = ""):
        # Do not intercept API routes or docs
        if full_path.startswith(("api/", "docs", "health")):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        return FileResponse(_INDEX)






