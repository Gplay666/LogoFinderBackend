#!/usr/bin/env python3
"""
Захват кадров из видеопотока (HLS .m3u8 / DASH .mpd) с заданным FPS,
инференс YOLO (детекция лого), отображение кадров с боксами и
отправка POST-уведомлений о детекциях на указанный API.

Архитектура (producer / consumer на потоках):
    1) Поток захвата   — читает кадры из стрима как можно быстрее (чтобы не
                         копился буфер), сэмплирует их до нужного FPS и кладёт
                         в очередь. Очередь имеет ограниченный размер и при
                         переполнении ВЫБРАСЫВАЕТ самые старые кадры.
    2) Поток инференса — забирает кадр(ы) из очереди (опционально батчем),
                         прогоняет через YOLO, рисует боксы, и, если
                         уверенность превышает порог, отправляет событие на API.
    3) Главный поток   — показывает последний проанализированный кадр
                         (cv2.imshow обязан жить в главном потоке), ресайзит
                         окно до 720p, ловит выход по 'q'.

Пример запуска:
    python stream_capture_yolo.py \
        --url "https://vgtrkregion-reg.cdnvideo.ru/vgtrk/0/russia1-hd/index.m3u8" \
        --model logo_detect_best.pt --fps 2 \
        --api-url "http://localhost:8000/detections/" \
        --channel "Россия 1"

    python stream_capture_yolo.py \
        --url "https://edge1.1internet.tv/dash-live2/streams/1tv-dvr/1tvdash.mpd" \
        --model logo_detect_best.pt --fps 2 --conf 0.3 --device 0 \
        --api-url "http://localhost:8000/detections/" \
        --channel "Первый канал" --api-conf 0.4

Требования:
    pip install opencv-python ultralytics requests
    В системе должен быть ffmpeg (для чтения HLS/DASH бэкендом OpenCV).
"""
import argparse
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

import cv2
import requests
from ultralytics import YOLO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("stream_capture")

# Целевая высота окна показа (720p).
DISPLAY_HEIGHT = 720


# --------------------------------------------------------------------------- #
#  Вспомогательные структуры для обмена кадрами между потоками
# --------------------------------------------------------------------------- #
class FrameQueue:
    """Потокобезопасная очередь ограниченного размера с автодропом старых кадров."""

    def __init__(self, maxsize: int):
        self._dq = deque(maxlen=maxsize)
        self._cond = threading.Condition()
        self.dropped = 0

    def put(self, item):
        with self._cond:
            if len(self._dq) == self._dq.maxlen:
                self.dropped += 1
            self._dq.append(item)
            self._cond.notify()

    def get_batch(self, max_items: int, timeout: float):
        with self._cond:
            if not self._dq:
                self._cond.wait(timeout)
            items = []
            while self._dq and len(items) < max_items:
                items.append(self._dq.popleft())
            return items


class LatestFrame:
    """Держатель одного (самого свежего) проанализированного кадра для показа."""

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()

    def set(self, frame):
        with self._lock:
            self._frame = frame

    def get(self):
        with self._lock:
            return self._frame


# --------------------------------------------------------------------------- #
#  Поток захвата кадров из стрима
# --------------------------------------------------------------------------- #
def capture_worker(url, target_fps, frame_queue, stop_event, reconnect_delay):
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "reconnect=1;reconnect_streamed=1;reconnect_delay_max=5;timeout=20000000"
    interval = 1.0 / target_fps if target_fps > 0 else 0.0

    while not stop_event.is_set():
        cap = None
        try:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "hwaccel=cuda;hwaccel_output_format=cuda"
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                raise RuntimeError(f"Не удалось открыть поток: {url}")

            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            log.info("Поток открыт: %s", url)
            last_capture_time = 0.0

            while not stop_event.is_set():
                ret, frame = cap.read()
                if not ret or frame is None:
                    log.warning("Не удалось прочитать кадр, поток мог оборваться")
                    break

                now = time.monotonic()
                if now - last_capture_time < interval:
                    continue
                last_capture_time = now

                frame_queue.put((frame, now))

        except Exception as e:
            log.error("Ошибка потока: %s", e)
        finally:
            if cap is not None:
                cap.release()

        if stop_event.is_set():
            break

        log.info("Переподключение через %.1f сек...", reconnect_delay)
        stop_event.wait(reconnect_delay)


# --------------------------------------------------------------------------- #
#  Отправка события обнаружения на API
# --------------------------------------------------------------------------- #
def send_detection(api_url, channel, company, confidence, detected_at=None):
    """
    POST-запрос к серверу мониторинга логотипов.
    Возвращает True при успехе (статус 2xx), иначе False.
    """
    if detected_at is None:
        detected_at = datetime.now(timezone.utc)

    payload = {
        "channel": channel,
        "detected_at": detected_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",  # ISO8601 с Z
        "company": company,
    }
    try:
        resp = requests.post(api_url, json=payload, timeout=5)
        if resp.status_code in (200, 201):
            log.info("Событие отправлено (conf=%.2f): %s", confidence, resp.text.strip())
            return True
        else:
            log.warning("Ошибка отправки (conf=%.2f): HTTP %d — %s",
                        confidence, resp.status_code, resp.text.strip())
            return False
    except Exception as e:
        log.error("Сетевая ошибка при отправке: %s", e)
        return False


# --------------------------------------------------------------------------- #
#  Поток инференса YOLO
# --------------------------------------------------------------------------- #
def inference_worker(model, frame_queue, display, stop_event,
                     imgsz, conf, device, batch_size,
                     save_conf, save_dir,
                     api_url, channel, company, api_conf):
    saved_count = 0
    while not stop_event.is_set():
        items = frame_queue.get_batch(batch_size, timeout=0.5)
        if not items:
            continue

        frames = [it[0] for it in items]

        try:
            t0 = time.monotonic()
            results = model.predict(
                source=frames,
                imgsz=imgsz,
                conf=conf,
                device=device,
                verbose=False,
            )
            dt = time.monotonic() - t0
            per_frame = dt / len(frames) if frames else dt
            infer_fps = 1.0 / per_frame if per_frame > 0 else 0.0

            for src_frame, res in zip(frames, results):
                n = len(res.boxes)
                annotated = res.plot()

                # Максимальная уверенность по кадру.
                max_conf = max((float(b.conf[0]) for b in res.boxes), default=0.0)

                # --- Сохранение кадров локально (старая логика) ---
                if save_conf is not None and max_conf >= save_conf:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    base = os.path.join(save_dir, f"{ts}_c{max_conf:.2f}")
                    try:
                        cv2.imwrite(f"{base}_raw.jpg", src_frame)
                        cv2.imwrite(f"{base}_det.jpg", annotated)
                        saved_count += 1
                        log.info("Сохранено (conf=%.2f): %s_{raw,det}.jpg [всего %d]",
                                 max_conf, base, saved_count)
                    except Exception as e:
                        log.error("Не удалось сохранить кадр: %s", e)

                # --- Отправка на API при превышении порога api_conf ---
                if api_url and max_conf >= api_conf:
                    # Используем текущее время (UTC) как время детекции
                    send_detection(api_url, channel, company, max_conf)

                # Оверлей с телеметрией.
                cv2.putText(
                    annotated,
                    f"objects: {n}  infer: {infer_fps:.1f} fps  dropped: {frame_queue.dropped}",
                    (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

                display.set(annotated)

                if n:
                    dets = [
                        f"{res.names[int(b.cls[0])]}={float(b.conf[0]):.2f}"
                        for b in res.boxes
                    ]
                    log.info("Найдено %d: %s", n, ", ".join(dets))

        except Exception as e:
            log.error("Ошибка инференса: %s", e)


# --------------------------------------------------------------------------- #
#  Ресайз кадра до 720p по высоте (с сохранением пропорций)
# --------------------------------------------------------------------------- #
def resize_for_display(frame, target_h=DISPLAY_HEIGHT):
    h, w = frame.shape[:2]
    if h == target_h:
        return frame
    scale = target_h / h
    new_w = max(1, int(round(w * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    return cv2.resize(frame, (new_w, target_h), interpolation=interp)


# --------------------------------------------------------------------------- #
#  Основная логика
# --------------------------------------------------------------------------- #
def run(args):
    log.info("Загрузка модели: %s", args.model)
    model = YOLO(args.model)

    stop_event = threading.Event()
    frame_queue = FrameQueue(maxsize=max(2, args.batch * 2))
    display = LatestFrame()

    save_conf = args.save_conf
    if save_conf is not None:
        os.makedirs(args.save_dir, exist_ok=True)
        log.info("Сохранение кадров при conf >= %.2f в папку: %s",
                 save_conf, os.path.abspath(args.save_dir))

    # Валидация API параметров
    api_url = args.api_url
    if api_url:
        log.info("Отправка событий на %s при conf >= %.2f (канал: %s, компания: %s)",
                 api_url, args.api_conf, args.channel, args.company)

    cap_thread = threading.Thread(
        target=capture_worker,
        args=(args.url, args.fps, frame_queue, stop_event, args.reconnect_delay),
        daemon=True,
    )
    inf_thread = threading.Thread(
        target=inference_worker,
        args=(model, frame_queue, display, stop_event,
              args.imgsz, args.conf, args.device, args.batch,
              save_conf, args.save_dir,
              api_url, args.channel, args.company, args.api_conf),
        daemon=True,
    )

    cap_thread.start()
    inf_thread.start()

    window_created = False
    log.info("Ожидание первого проанализированного кадра...")

    try:
        while not stop_event.is_set():
            frame = display.get()

            if frame is not None:
                if not window_created:
                    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(
                        args.window_name,
                        int(DISPLAY_HEIGHT * 16 / 9), DISPLAY_HEIGHT,
                    )
                    window_created = True
                cv2.imshow(args.window_name, resize_for_display(frame))

            key = cv2.waitKey(30) & 0xFF
            if window_created and key == ord("q"):
                log.info("Остановлено пользователем")
                break

            if not cap_thread.is_alive() and not inf_thread.is_alive():
                log.error("Рабочие потоки завершились")
                break
    finally:
        stop_event.set()
        cap_thread.join(timeout=2.0)
        inf_thread.join(timeout=2.0)
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="Захват HLS/DASH потока + YOLO-детекция лого с показом боксов и отправкой на API"
    )
    parser.add_argument("--url", required=True, help="URL потока (.m3u8 или .mpd)")
    parser.add_argument("--model", default="logo_detect_best.pt",
                        help="Путь к чекпоинту YOLO (.pt)")
    parser.add_argument("--fps", type=float, default=2.0,
                        help="Сколько кадров в секунду захватывать (по умолчанию 2)")
    parser.add_argument("--imgsz", type=int, default=1280,
                        help="Размер входа модели (должен совпадать с train, тут 1280)")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="Порог уверенности детекции")
    parser.add_argument("--device", default=None,
                        help="Устройство инференса: 'cpu', '0', 'cuda' и т.п. (авто)")
    parser.add_argument("--batch", type=int, default=1,
                        help="Размер батча кадров на инференс (по умолчанию 1)")
    parser.add_argument("--save-conf", type=float, default=0.5,
                        help="Сохранять кадры, если уверенность >= этого порога "
                             "(по умолчанию 0.5; отрицательное число отключает сохранение)")
    parser.add_argument("--save-dir", default="detections",
                        help="Папка для сохранённых кадров")

    # Новые аргументы для API
    parser.add_argument("--api-url", default=None,
                        help="URL для отправки POST /detections/ (если не указан, отправка отключена)")
    parser.add_argument("--channel", default="unknown",
                        help="Название телеканала (передаётся в JSON)")
    parser.add_argument("--company", default="x5",
                        help="Название компании (по умолчанию x5)")
    parser.add_argument("--api-conf", type=float, default=0.5,
                        help="Порог уверенности для отправки события (по умолчанию 0.5)")

    parser.add_argument("--window-name", default="stream", help="Название окна")
    parser.add_argument("--reconnect-delay", type=float, default=5.0,
                        help="Задержка перед переподключением, сек")
    args = parser.parse_args()

    if args.batch < 1:
        args.batch = 1

    if args.save_conf is not None and args.save_conf < 0:
        args.save_conf = None

    try:
        run(args)
    except KeyboardInterrupt:
        log.info("Прервано пользователем (Ctrl+C)")
        cv2.destroyAllWindows()
        sys.exit(0)


if __name__ == "__main__":
    main()