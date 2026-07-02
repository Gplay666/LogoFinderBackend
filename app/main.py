# app/main.py
import logging
import uvicorn
from fastapi import FastAPI
from app.api.router import router
from app.core.config import settings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Logo Detection Monitor",
    description="Сервис мониторинга появления логотипов в ТВ-эфире",
    version="0.1.0",
)

app.include_router(router)


@app.on_event("startup")
async def startup():
    logger.info("Приложение запущено")
    logger.info(f"Подключение к БД: {settings.DATABASE_URL}")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Приложение остановлено")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)