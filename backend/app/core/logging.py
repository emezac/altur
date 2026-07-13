import contextvars
import logging
import json
import sys
from app.core.config import settings

# Variables de contexto asíncronas para rastreo
request_id_ctx = contextvars.ContextVar("request_id", default="")
call_id_ctx = contextvars.ContextVar("call_id", default="")

class StructuredJSONFormatter(logging.Formatter):
    """
    Formateador de logs en formato JSON para entornos de producción/cloud.
    """
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.000Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
            "call_id": call_id_ctx.get(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

class CleanTextFormatter(logging.Formatter):
    """
    Formateador de texto limpio y legible para desarrollo local.
    """
    def format(self, record):
        req_id = request_id_ctx.get()
        call_id = call_id_ctx.get()
        ctx_str = ""
        if req_id or call_id:
            ctx_str = f" [{f'req:{req_id}' if req_id else ''}{' ' if req_id and call_id else ''}{f'call:{call_id}' if call_id else ''}]"
        
        msg = f"{self.formatTime(record, '%H:%M:%S')} | {record.levelname:<7} | {record.name} - {record.getMessage()}{ctx_str}"
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"
        return msg

def setup_logging():
    root_logger = logging.getLogger()
    
    # Limpiar handlers existentes
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    
    if settings.APP_ENV == "cloud":
        handler.setFormatter(StructuredJSONFormatter())
        root_logger.setLevel(logging.INFO)
    else:
        handler.setFormatter(CleanTextFormatter())
        root_logger.setLevel(logging.DEBUG)
        
    root_logger.addHandler(handler)
    
    # Evitar logs ruidosos de terceros en DEBUG
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
