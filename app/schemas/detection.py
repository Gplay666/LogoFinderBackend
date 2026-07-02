# app/schemas/detection.py
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class DetectionCreate(BaseModel):
    """Схема для создания события обнаружения."""
    channel: str = Field(..., min_length=1, description="Название канала")
    detected_at: datetime = Field(..., description="Момент обнаружения (ISO 8601, с timezone)")
    company: str = Field(default="x5", min_length=1, description="Компания (по умолчанию X5)")

    @field_validator("channel")
    @classmethod
    def channel_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("channel не может быть пустым или состоять только из пробелов")
        return v.strip()

    @field_validator("detected_at")
    @classmethod
    def detected_at_must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("detected_at должен содержать информацию о часовом поясе (timezone-aware)")
        return v


class DetectionResponse(BaseModel):
    """Схема ответа с событием."""
    id: int
    channel: str
    detected_at: datetime
    created_at: datetime
    company: str

    model_config = {"from_attributes": True}