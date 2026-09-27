"""MegaDetector v6 (Ultralytics YOLO) — "is there an animal in this frame?" on CPU.

We load the MegaDetector v6 weights directly with Ultralytics instead of via
PytorchWildlife, which unconditionally imports a bioacoustics module that drags
in librosa/torchaudio/soundfile we never use. Weights cache to the models volume.
"""
from __future__ import annotations

import os
import threading

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# MegaDetector category ids: 0 = animal, 1 = person, 2 = vehicle
ANIMAL_CATEGORY = 0
_MODEL_URL = "https://zenodo.org/records/15398270/files/MDV6-yolov9-c.pt?download=1"
_MODEL_FILE = "MDV6-yolov9-c.pt"

# The box confidence the detector is asked for. Ultralytics answers only boxes over
# its default 0.25 unless told otherwise, which made the 0.10 "keep faint animals"
# threshold (empty_filter) and grouping's 0.2 dead letters. Keep it below both.
DETECT_CONF = 0.05

_model = None
_lock = threading.Lock()


def download(url: str, path: str, *, timeout: float, what: str) -> None:
    """Fetch model weights to `path`, never leaving a half-written file there.

    It streams into `<path>.part` and moves it into place only once the whole file
    has come, checked against the length the server announced, so a dropped
    connection leaves nothing that a later run would load as if it were complete.
    """
    part = path + ".part"
    log.info(f"{what}.downloading", url=url)
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as r:
            r.raise_for_status()
            expected = int(r.headers.get("content-length") or 0)
            with open(part, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        got = os.path.getsize(part)
        if expected and got != expected:
            raise OSError(f"download cut short: {got} of {expected} bytes")
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    log.info(f"{what}.downloaded", path=path, bytes=os.path.getsize(path))


def discard(path: str, what: str, error: Exception) -> None:
    """Weights that would not load are removed, so the next run downloads them again."""
    log.error(f"{what}.bad_weights", path=path, error=str(error)[:300])
    try:
        os.remove(path)
    except OSError:
        pass


def _weights_path() -> str:
    os.makedirs(settings.models_root, exist_ok=True)
    path = os.path.join(settings.models_root, _MODEL_FILE)
    if not os.path.exists(path):
        download(_MODEL_URL, path, timeout=300, what="detector")
    return path


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from ultralytics import YOLO

                path = _weights_path()
                log.info("detector.loading", model=_MODEL_FILE, device="cpu")
                try:
                    _model = YOLO(path)
                except Exception as e:
                    discard(path, "detector", e)
                    raise
                log.info("detector.loaded")
    return _model


def load() -> None:
    """Load the model now (the AI pass does this once, before touching any photo)."""
    _get_model()


def detect_animals(image_path: str, conf: float = DETECT_CONF) -> list[dict]:
    """Return [{confidence, bbox}] for animal detections in the image."""
    model = _get_model()
    results = model.predict(image_path, device="cpu", verbose=False, conf=conf)
    out: list[dict] = []
    for r in results:
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            continue
        for i in range(len(boxes)):
            if int(boxes.cls[i]) == ANIMAL_CATEGORY:
                out.append({
                    "confidence": float(boxes.conf[i]),
                    "bbox": [float(v) for v in boxes.xyxy[i]],
                })
    return out
