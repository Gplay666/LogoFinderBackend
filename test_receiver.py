#!/usr/bin/env python3
"""
Простой тестовый приёмник видеофрагментов.
Запускает HTTP-сервер на порту 9000 и сохраняет полученные POST-запросы
в папку received_segments.
"""

import asyncio
import logging
from pathlib import Path
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("receiver")

SAVE_DIR = Path("received_segments")
SAVE_DIR.mkdir(exist_ok=True)

# Максимальный размер запроса: 100 МБ
MAX_SIZE = 100 * 1024 * 1024


async def handle_upload(request: web.Request) -> web.Response:
    """Обрабатывает POST-запрос с телом видеофайла."""
    data = await request.read()
    existing = list(SAVE_DIR.glob("segment_*.mp4"))
    next_num = len(existing) + 1
    filename = f"segment_{next_num:05d}.mp4"
    filepath = SAVE_DIR / filename

    with open(filepath, "wb") as f:
        f.write(data)

    # Проверяем, что файл действительно записан полностью
    actual_size = filepath.stat().st_size
    if actual_size != len(data):
        logger.warning(
            f"Размер файла {filename} ({actual_size}) не совпадает с полученным ({len(data)})"
        )

    logger.info(f"Получен файл: {filename}, размер: {actual_size} байт")
    return web.Response(text=f"OK: {filename}")


async def main():
    app = web.Application(client_max_size=MAX_SIZE)
    app.router.add_post("/upload", handle_upload)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 9000)
    await site.start()

    logger.info(f"Приёмник запущен на http://0.0.0.0:9000/upload (лимит {MAX_SIZE // (1024*1024)} МБ)")
    logger.info(f"Файлы сохраняются в: {SAVE_DIR.resolve()}")

    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Остановка приёмника...")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())