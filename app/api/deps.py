# app/api/deps.py
import logging
from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.repositories.detection_repo import DetectionRepository
from app.services.detection_service import DetectionService
from app.services.detection_adapter import NeuralNetworkAdapter

logger = logging.getLogger(__name__)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Асинхронный генератор сессии БД."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Ошибка при работе с сессией БД: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_detection_repo(session: AsyncSession = Depends(get_db_session)) -> DetectionRepository:
    """Вернуть экземпляр репозитория."""
    return DetectionRepository(session)


async def get_detection_service(repo: DetectionRepository = Depends(get_detection_repo)) -> DetectionService:
    """Вернуть экземпляр сервиса."""
    return DetectionService(repo)


def get_neural_network_adapter() -> NeuralNetworkAdapter:
    """Вернуть экземпляр адаптера (не требует асинхронности)."""
    return NeuralNetworkAdapter()