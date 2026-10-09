import base64
from pathlib import Path

import requests

from .models import Source


def check_vision_model(model: str, base_url: str) -> None:
    response = requests.post(base_url.rstrip("/") + "/api/show", json={"model": model}, timeout=30)
    response.raise_for_status()
    if "vision" not in response.json().get("capabilities", []):
        raise ValueError(f"{model} не поддерживает картинки; выберите vision-модель или --vision off")


def frame_changes(sources: list[Source], folder: Path) -> dict[str, float]:
    """Cheap pixel changes help notice changes hidden from OCR, such as colors."""
    import cv2
    import numpy as np

    previous = None
    changes = {}
    for source in sorted(sources, key=lambda item: item.start):
        if not source.image:
            continue
        frame = cv2.imread(str(folder / source.image))
        if frame is None:
            raise ValueError(f"Не удалось прочитать {source.image}")
        thumbnail = cv2.resize(frame, (256, 144), interpolation=cv2.INTER_AREA)
        changes[source.id] = (
            1.0 if previous is None else round(float(np.mean(
                np.max(cv2.absdiff(thumbnail, previous), axis=2) > 25
            )), 4)
        )
        previous = thumbnail
    return changes


def encode_frames(sources: list[Source], ids: list[str], folder: Path, max_side: int):
    import cv2

    by_id = {source.id: source for source in sources if source.image}
    images = []
    metadata = []
    for source_id in dict.fromkeys(ids):
        source = by_id[source_id]
        frame = cv2.imread(str(folder / source.image))
        if frame is None:
            raise ValueError(f"Не удалось прочитать {source.image}")
        height, width = frame.shape[:2]
        scale = min(1, max_side / max(width, height))
        if scale < 1:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)),
                               interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError(f"Не удалось подготовить {source.image}")
        images.append(base64.b64encode(encoded.tobytes()).decode("ascii"))
        metadata.append({"id": source.id, "start": source.start,
                         "width": frame.shape[1], "height": frame.shape[0]})
    return images, metadata
