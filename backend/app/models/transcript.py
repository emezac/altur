import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Text, JSON, ForeignKey, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), unique=True, index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    turns: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    stt_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    stt_model: Mapped[str] = mapped_column(String(100), nullable=False)
    stt_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    call: Mapped["Call"] = relationship(back_populates="transcript")
