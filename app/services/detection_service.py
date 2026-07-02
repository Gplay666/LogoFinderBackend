# app/services/detection_service.py
import logging
from datetime import datetime
from typing import Sequence
from app.repositories.detection_repo import DetectionRepository
from app.schemas.detection import DetectionCreate, DetectionResponse

logger = logging.getLogger(__name__)


class DetectionService:
    """Сервис для работы с событиями обнаружения."""

    def __init__(self, repo: DetectionRepository):
        self.repo = repo

    async def add_detection(self, data: DetectionCreate) -> DetectionResponse:
        """Добавить новое событие и вернуть его представление."""
        detection = await self.repo.create(data)
        return DetectionResponse.model_validate(detection)

    async def get_detections(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[DetectionResponse]:
        """Получить список событий."""
        detections = await self.repo.get_list(
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
            offset=offset,
        )
        return [DetectionResponse.model_validate(d) for d in detections]

    async def get_total_count(self) -> int:
        return await self.repo.count()

    async def get_last_detection(self) -> DetectionResponse | None:
        detection = await self.repo.get_last()
        if detection:
            return DetectionResponse.model_validate(detection)
        return None