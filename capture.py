#!/usr/bin/env python3
"""
Захват видеопотока и нарезка на сегменты.
"""

import asyncio
import argparse
import logging
from app.services.stream_capture import StreamCapture

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("capture")


async def main():
    parser = argparse.ArgumentParser(description="Захват видеопотока")
    parser.add_argument("--stream", required=True, help="URL видеопотока")
    parser.add_argument("--target", required=True, help="URL для отправки видео")
    parser.add_argument("--duration", type=int, default=5, help="Длительность сегмента (с)")
    parser.add_argument(
        "--ffmpeg-loglevel", default="warning",
        choices=["quiet", "panic", "fatal", "error", "warning", "info", "verbose", "debug"],
        help="Уровень логирования ffmpeg"
    )
    parser.add_argument("--ffmpeg-args", default="", help="Дополнительные аргументы ffmpeg")
    args = parser.parse_args()

    capture = StreamCapture()
    try:
        await capture.start(
            args.stream,
            args.target,
            args.duration,
            ffmpeg_loglevel=args.ffmpeg_loglevel,
            ffmpeg_extra_args=args.ffmpeg_args,
        )
        logger.info("Захват запущен. Нажмите Ctrl+C для остановки.")
        # Ожидание с подавлением CancelledError
        while True:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        await capture.stop()
        logger.info("Захват остановлен")


if __name__ == "__main__":
    asyncio.run(main())