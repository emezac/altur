import uuid
import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)

class AppError(Exception):
    """
    Base exception for controlled application errors.
    """
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

async def app_error_handler(request: Request, exc: AppError):
    """
    Handler for controlled AppError exceptions.
    """
    req_id = request_id_ctx.get() or str(uuid.uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": req_id
            }
        }
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handler for schema validation errors (Pydantic / FastAPI).
    """
    req_id = request_id_ctx.get() or str(uuid.uuid4())
    errors = exc.errors()
    error_details = []
    for error in errors:
        loc = " -> ".join(str(l) for l in error.get("loc", []))
        msg = error.get("msg", "")
        error_details.append(f"{loc}: {msg}")
    
    message = "Validation errors: " + "; ".join(error_details)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": message,
                "request_id": req_id
            }
        }
    )

async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler. Delegates HTTPExceptions to Starlette's default
    response so that 404s from StaticFiles are returned correctly, not swallowed.
    """
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    req_id = request_id_ctx.get() or str(uuid.uuid4())
    logger.exception(f"Unhandled exception detected in request: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal server error occurred.",
                "request_id": req_id
            }
        }
    )
