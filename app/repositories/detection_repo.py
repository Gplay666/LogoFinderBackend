# app/repositories/detection_repo.py
import logging
from datetime import datetime
from typing import Sequence
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from app.models.detection import Detection
from app.schemas.detection import DetectionCreate

logger = logging.getLogger(__name__)


class DetectionRepository:
    """Репозиторий для работы с таблицей detections."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: DetectionCreate) -> Detection:
        """Создать новую запись о детекции."""
        detection = Detection(
            channel=data.channel,
            detected_at=data.detected_at,
            company=data.company,
        )
        self.session.add(detection)
        try:
            await self.session.commit()
            await self.session.refresh(detection)
            logger.info(f"Сохранено событие: {detection}")
            return detection
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Ошибка при сохранении события: {e}")
            raise

    async def get_list(
        self,
        *,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Detection]:
        """Получить список событий с фильтрацией и пагинацией."""
        stmt = select(Detection).order_by(desc(Detection.detected_at))
        if from_dt is not None:
            stmt = stmt.where(Detection.detected_at >= from_dt)
        if to_dt is not None:
            stmt = stmt.where(Detection.detected_at <= to_dt)
        stmt = stmt.offset(offset).limit(limit)
        try:
            result = await self.session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при выборке событий: {e}")
            raise