import asyncio
import os
import shutil
import tempfile
import logging
import time
import psutil
from pathlib import Path
from typing import Optional, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)


class StreamCapture:
    """
    Захватывает видеопоток, нарезает на сегменты, отправляет на target_url.
    Собирает метрики: время обработки, время отправки, загрузка CPU и памяти.
    """
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.temp_dir: Optional[Path] = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._sender_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._send_queue: asyncio.Queue[Path] = asyncio.Queue()
        self._processed_files: set[Path] = set()
        self._target_url: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # Метрики
        self.metrics: Dict[str, Any] = {
            "segments_captured": 0,
            "segments_sent": 0,
            "send_errors": 0,
            "total_capture_time": 0.0,
            "total_send_time": 0.0,
            "current_cpu_percent": 0.0,
            "current_memory_mb": 0.0,
            "ffmpeg_cpu_percent": 0.0,
            "ffmpeg_memory_mb": 0.0,
        }
        self._start_time = time.time()

    async def start(
        self,
        stream_url: str,
        target_url: str,
        segment_duration: int = 5,
        ffmpeg_loglevel: str = "warning",  # теперь по умолчанию warning, чтобы видеть проблемы
        ffmpeg_extra_args: Optional[str] = None,
    ):
        if self._running:
            raise RuntimeError("Захват уже запущен")

        self._target_url = target_url
        self._session = aiohttp.ClientSession()

        self.temp_dir = Path(tempfile.mkdtemp(prefix="logo_segments_"))
        logger.info(f"Временная директория: {self.temp_dir}")

        output_template = str(self.temp_dir / "segment_%05d.mp4")

        # Базовая команда с улучшенными параметрами для live DASH
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", ffmpeg_loglevel,
            # Опции для стабильного чтения live-потоков
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            # Входной поток
            "-i", stream_url,
            # Копируем все дорожки без перекодирования
            "-c", "copy",
            "-map", "0",
            # Сегментация
            "-f", "segment",
            "-segment_time", str(segment_duration),
            "-reset_timestamps", "1",
            "-segment_format", "mp4",
        ]

        # Добавляем любые дополнительные аргументы, переданные пользователем
        if ffmpeg_extra_args:
            cmd.extend(ffmpeg_extra_args.split())

        cmd.append(output_template)

        logger.info(f"Запуск ffmpeg: {' '.join(cmd)}")
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        self._running = True

        self._monitor_task = asyncio.create_task(self._monitor())
        self._sender_task = asyncio.create_task(self._sender())
        self._metrics_task = asyncio.create_task(self._metrics_reporter())
        # Выводим stderr в лог полностью (с уровнем WARNING)
        asyncio.create_task(self._log_stderr())

    async def stop(self):
        if not self._running:
            return

        logger.info("Остановка захвата...")
        self._running = False

        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("ffmpeg не завершился, убиваем")
                self.process.kill()
                await self.process.wait()

        for task in [self._monitor_task, self._sender_task, self._metrics_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._session:
            await self._session.close()

        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.info("Временная директория удалена")

        uptime = time.time() - self._start_time
        logger.info("=== Итоговые метрики ===")
        logger.info(f"Время работы: {uptime:.1f} с")
        logger.info(f"Сегментов захвачено: {self.metrics['segments_captured']}")
        logger.info(f"Успешно отправлено: {self.metrics['segments_sent']}")
        logger.info(f"Ошибок отправки: {self.metrics['send_errors']}")
        if self.metrics['segments_captured'] > 0:
            logger.info(f"Среднее время захвата: {(self.metrics['total_capture_time'] / self.metrics['segments_captured']):.3f} с")
        if self.metrics['segments_sent'] > 0:
            logger.info(f"Среднее время отправки: {(self.metrics['total_send_time'] / self.metrics['segments_sent']):.3f} с")

    async def _monitor(self):
        while self._running:
            if self.temp_dir and self.temp_dir.exists():
                for fp in sorted(self.temp_dir.glob("segment_*.mp4")):
                    if fp not in self._processed_files and fp.stat().st_size > 0:
                        creation_time = fp.stat().st_ctime
                        capture_duration = time.time() - creation_time
                        self.metrics["total_capture_time"] += capture_duration
                        self.metrics["segments_captured"] += 1
                        self._processed_files.add(fp)
                        await self._send_queue.put(fp)
                        logger.info(f"Новый сегмент: {fp.name} (захват за {capture_duration:.3f}с)")
            await asyncio.sleep(0.5)

    async def _sender(self):
        while self._running or not self._send_queue.empty():
            try:
                file_path = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            send_start = time.time()
            success = await self._send_file(file_path)
            send_duration = time.time() - send_start
            self.metrics["total_send_time"] += send_duration

            if success:
                self.metrics["segments_sent"] += 1
                logger.info(f"Файл {file_path.name} отправлен за {send_duration:.3f}с")
            else:
                self.metrics["send_errors"] += 1
                logger.error(f"Ошибка отправки {file_path.name}")

            try:
                os.remove(file_path)
                logger.debug(f"Файл {file_path.name} удалён")
            except OSError as e:
                logger.warning(f"Не удалось удалить {file_path}: {e}")

    async def _send_file(self, file_path: Path) -> bool:
        if not self._session:
            return False
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            async with self._session.post(self._target_url, data=data) as resp:
                if resp.status == 200:
                    return True
                else:
                    logger.warning(f"Ответ сервера: {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Ошибка при отправке: {e}")
            return False

    async def _metrics_reporter(self, interval: int = 10):
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            self._update_resource_usage()
            logger.info(
                f"Метрики: CPU={self.metrics['current_cpu_percent']:.1f}% "
                f"(ffmpeg={self.metrics['ffmpeg_cpu_percent']:.1f}%), "
                f"RAM={self.metrics['current_memory_mb']:.1f}MB "
                f"(ffmpeg={self.metrics['ffmpeg_memory_mb']:.1f}MB), "
                f"отправлено={self.metrics['segments_sent']}, "
                f"ошибок={self.metrics['send_errors']}"
            )

    def _update_resource_usage(self):
        proc = psutil.Process(os.getpid())
        self.metrics["current_cpu_percent"] = proc.cpu_percent()
        mem_info = proc.memory_info()
        self.metrics["current_memory_mb"] = mem_info.rss / (1024 * 1024)

        if self.process and self.process.returncode is None:
            try:
                ffmpeg_proc = psutil.Process(self.process.pid)
                self.metrics["ffmpeg_cpu_percent"] = ffmpeg_proc.cpu_percent()
                ffmpeg_mem = ffmpeg_proc.memory_info()
                self.metrics["ffmpeg_memory_mb"] = ffmpeg_mem.rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self.metrics["ffmpeg_cpu_percent"] = 0.0
                self.metrics["ffmpeg_memory_mb"] = 0.0

    async def _log_stderr(self):
        if not self.process or not self.process.stderr:
            return
        while self._running:
            line = await self.process.stderr.readline()
            if not line:
                break
            # Все сообщения stderr выводим как WARNING в лог приложения
            logger.warning(f"ffmpeg: {line.decode().strip()}")