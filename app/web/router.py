from fastapi import APIRouter, Request, Depends, Query
from jinja2 import Environment, FileSystemLoader
from starlette.responses import HTMLResponse
from app.services.detection_service import DetectionService
from app.api.deps import get_detection_service

router = APIRouter()

# Окружение Jinja2 с отключённым кэшем
env = Environment(loader=FileSystemLoader("app/templates"), cache_size=0)


def render_template(name: str, request: Request, **context) -> HTMLResponse:
    """Рендеринг шаблона с передачей request и дополнительных переменных."""
    template = env.get_template(name)
    return HTMLResponse(template.render(request=request, **context))


@router.get("/")
async def index(
    request: Request,
    service: DetectionService = Depends(get_detection_service),
):
    total_count = 0
    last_detected_at = "—"
    try:
        total_count = await service.get_total_count()
        last_detection = await service.get_last_detection()
        if last_detection:
            last_detected_at = last_detection.detected_at.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return render_template(
        "index.html",
        request,
        last_detected_at=last_detected_at,
        total_count=total_count,
    )


@router.get("/events/")
async def get_events(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: DetectionService = Depends(get_detection_service),
):
    try:
        events = await service.get_detections(limit=limit, offset=offset)
    except Exception:
        events = []
    return render_template("events.html", request, events=events)