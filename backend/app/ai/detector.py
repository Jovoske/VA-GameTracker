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

_model = None
_lock = threading.Lock()


def _weights_path() -> str:
    os.makedirs(settings.models_root, exist_ok=True)
    path = os.path.join(settings.models_root, _MODEL_FILE)
    if not os.path.exists(path):
        log.info("detector.downloading", url=_MODEL_URL)
        with httpx.stream("GET", _MODEL_URL, follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        log.info("detector.downloaded", path=path, bytes=os.path.getsize(path))
    return path


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from ultralytics import YOLO

                log.info("detector.loading", model=_MODEL_FILE, device="cpu")
                _model = YOLO(_weights_path())
                log.info("detector.loaded")
    return _model


def detect_animals(image_path: str) -> list[dict]:
    """Return [{confidence, bbox}] for animal detections in the image."""
    model = _get_model()
    results = model.predict(image_path, device="cpu", verbose=False)
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
