import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.logging import setup_logging, request_id_ctx
from app.core.exceptions import (
    AppError,
    app_error_handler,
    validation_exception_handler,
    global_exception_handler,
)
from app.api.health import router as health_router

# Inicializar logging inmediatamente al cargar el módulo
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lógica de inicio (si se requiere)
    yield
    # Lógica de apagado (si se requiere)

app = FastAPI(
    title="Call Analyzer API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None
)

# Middleware de rastreo de peticiones (Request Tracing)
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_ctx.set(req_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

# Configuración de CORS
origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar manejadores de excepciones personalizados
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Registrar routers de la API
app.include_router(health_router, tags=["Health"])
