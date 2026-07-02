# app/main.py
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.router import router as api_router
from app.web.router import router as web_router
from app.core.config import settings

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

# Статика
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# API
app.include_router(api_router)

# Веб-интерфейс
app.include_router(web_router)

@app.on_event("startup")
async def startup():
    logger.info("Приложение запущено")
    logger.info(f"Подключение к БД: {settings.DATABASE_URL}")

@app.on_event("shutdown")
async def shutdown():
    logger.info("Приложение остановлено")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)