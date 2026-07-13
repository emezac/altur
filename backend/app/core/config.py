from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # --- Entorno ---
    APP_ENV: str = "local_dev"

    # --- Base de Datos ---
    DATABASE_URL: str = "sqlite:///./dev.db"

    # --- Cola ---
    REDIS_URL: Optional[str] = None

    # --- Storage ---
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_PATH: str = "./data/audio"
    S3_BUCKET_NAME: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None
    S3_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # --- Proveedores ---
    STT_PROVIDER: str = "fake"
    LLM_PROVIDER: str = "fake"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_STT_MODEL: str = "whisper-1"
    OPENAI_LLM_MODEL: str = "gpt-4o-mini"

    # --- Feature Flags ---
    ENABLE_VAD_CHUNKING: bool = False
    ENABLE_PII_REDACTION: bool = False
    MAX_UPLOAD_MB: int = 100
    FAKE_PROCESSING_DELAY_SECONDS: float = 2.0

    # --- Seguridad / App ---
    SECRET_KEY: str = "change-me"
    CORS_ORIGINS: str = "http://localhost:5173"

    # Buscar el archivo .env tanto en el directorio actual como en el padre
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
