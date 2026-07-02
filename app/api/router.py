# app/api/router.py
from datetime import datetime
from typing import Sequence
from fastapi import APIRouter, Depends, Query, HTTPException, status
from app.schemas.detection import DetectionCreate, DetectionResponse
from app.services.detection_service import DetectionService
from app.services.detection_adapter import NeuralNetworkAdapter
from app.api.deps import get_detection_service, get_neural_network_adapter
import logging

router = APIRouter(prefix="/detections", tags=["Detections"])
logger = logging.getLogger(__name__)


@router.post("/", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    raw_data: dict,  # В будущем здесь может быть специфичная модель нейросети
    service: DetectionService = Depends(get_detection_service),
    adapter: NeuralNetworkAdapter = Depends(get_neural_network_adapter),
):
    """
    Зарегистрировать новое обнаружение логотипа.
    Принимает сырые данные от нейросети, преобразует через адаптер и сохраняет.
    """
    try:
        detection_data = adapter.transform(raw_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    try:
        result = await service.add_detection(detection_data)
        return result
    except Exception as e:
        logger.error(f"Ошибка создания детекции: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера")


@router.get("/", response_model=list[DetectionResponse])
async def get_detections(
    from_dt: datetime | None = Query(None, alias="from", description="Начальная граница detected_at"),
    to_dt: datetime | None = Query(None, alias="to", description="Конечная граница detected_at"),
    limit: int = Query(100, ge=1, le=1000, description="Максимальное количество записей"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    service: DetectionService = Depends(get_detection_service),
) -> Sequence[DetectionResponse]:
    """
    Получить список событий. Поддерживается фильтрация по временному диапазону и пагинация.
    Сортировка: detected_at DESC.
    """
    try:
        return await service.get_detections(
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"Ошибка получения детекций: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка при получении данных")