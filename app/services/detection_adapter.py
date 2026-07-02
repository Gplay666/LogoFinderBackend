# app/services/detection_adapter.py
from typing import Any
from app.schemas.detection import DetectionCreate
import logging

logger = logging.getLogger(__name__)


class NeuralNetworkAdapter:
    """
    Адаптер для преобразования сырых данных нейросети в стандартную схему DetectionCreate.
    MVP: предполагает, что данные приходят уже в правильном формате.
    При изменении контракта нейросети достаточно модифицировать только этот класс.
    """

    def transform(self, raw_data: Any) -> DetectionCreate:
        """
        Преобразует входные данные в DetectionCreate.
        Args:
            raw_data: данные в формате, предоставляемом нейросетью.
        Returns:
            Экземпляр DetectionCreate.
        Raises:
            ValueError: если данные не могут быть преобразованы.
        """
        # В MVP raw_data уже словарь, готовый к валидации
        if isinstance(raw_data, dict):
            try:
                return DetectionCreate(**raw_data)
            except Exception as e:
                logger.error(f"Ошибка адаптации данных: {e}")
                raise ValueError(f"Невозможно преобразовать данные: {e}")
        else:
            raise ValueError("Неподдерживаемый формат данных от нейросети")