# app/models/detection.py
from datetime import datetime, timezone
from sqlalchemy import BigInteger, String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    company: Mapped[str] = mapped_column(Text, nullable=False, default="x5", server_default="x5")

    def __repr__(self) -> str:
        return f"<Detection(id={self.id}, company='{self.company}', channel='{self.channel}', detected_at={self.detected_at})>"