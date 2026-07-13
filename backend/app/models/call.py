import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, Float, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", index=True)
    owner_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    transcript: Mapped[Optional["Transcript"]] = relationship(
        back_populates="call", 
        uselist=False, 
        cascade="all, delete-orphan"
    )
    summary: Mapped[Optional["Summary"]] = relationship(
        back_populates="call", 
        uselist=False, 
        cascade="all, delete-orphan"
    )
    tags: Mapped[List["CallTag"]] = relationship(
        back_populates="call", 
        cascade="all, delete-orphan"
    )
    overrides: Mapped[List["CallTagOverride"]] = relationship(
        back_populates="call", 
        cascade="all, delete-orphan"
    )
    events: Mapped[List["CallEvent"]] = relationship(
        back_populates="call", 
        cascade="all, delete-orphan"
    )
