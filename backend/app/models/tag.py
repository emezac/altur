import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

class CallTag(Base):
    __tablename__ = "call_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), index=True, nullable=False)
    tag_category: Mapped[str] = mapped_column(String(50), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="model")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    call: Mapped["Call"] = relationship(back_populates="tags")

class CallTagOverride(Base):
    __tablename__ = "call_tag_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), index=True, nullable=False)
    tag_category: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_value: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    new_value: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # 'changed' | 'added' | 'removed'
    reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    call: Mapped["Call"] = relationship(back_populates="overrides")
