"""MegaDetector v6 (Ultralytics YOLO) — "is there an animal in this frame?" on CPU.

We load the MegaDetector v6 weights directly with Ultralytics instead of via
PytorchWildlife, which unconditionally imports a bioacoustics module that drags
in librosa/torchaudio/soundfile we never use. Weights cache to the models volume.
"""
from __future__ import annotations

import json
import os
import pickle
import threading
import time
import zipfile
from datetime import datetime

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# MegaDetector category ids: 0 = animal, 1 = person, 2 = vehicle
ANIMAL_CATEGORY = 0
PERSON_CATEGORY = 1
VEHICLE_CATEGORY = 2
_MODEL_URL = "https://zenodo.org/records/15398270/files/MDV6-yolov9-c.pt?download=1"
_MODEL_FILE = "MDV6-yolov9-c.pt"

# The box confidence the detector is asked for. Ultralytics answers only boxes over
# its default 0.25 unless told otherwise, which made the 0.10 "keep faint animals"
# threshold (empty_filter) and grouping's 0.2 dead letters. Keep it below both.
DETECT_CONF = 0.05

_model = None
_lock = threading.Lock()

# Weights removed for failing to load are downloaded again at most this often, so a
# load that keeps failing never pulls the file (1.2 GB for the species model) on
# every 15-minute fetch while holding the pipeline up.
REDOWNLOAD_SECONDS = 24 * 3600

# What torch and ultralytics say when the file itself is broken (cut short, not a
# checkpoint at all), as opposed to the machine (memory) or the libraries.
_FILE_MARKERS = ("PytorchStreamReader", "invalid load key", "failed finding central directory",
                 "unexpected EOF", "file might be corrupted", "not a zip file")


class WeightsMismatch(ValueError):
    """The file loaded, but it does not fit the model (its head or most weights missing)."""


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


def bad_file(error: BaseException) -> bool:
    """Whether a load error says the weights file itself is broken.

    Only then is the file worth fetching again. Running out of memory (the server
    runs SQL Server too), or a library missing or at another version, says nothing
    about the file: a new copy would fail the same way, after a 1.2 GB download.
    """
    if isinstance(error, (MemoryError, ImportError)):
        return False
    if isinstance(error, (pickle.UnpicklingError, EOFError, zipfile.BadZipFile, WeightsMismatch)):
        return True
    return isinstance(error, RuntimeError) and any(m in str(error) for m in _FILE_MARKERS)


def _marker(path: str) -> str:
    return path + ".bad"


def _read_marker(path: str) -> dict:
    try:
        with open(_marker(path), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_marker(path: str, **fields) -> None:
    data = {**_read_marker(path), **fields}
    try:
        with open(_marker(path), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def discard(path: str, what: str, error: Exception) -> None:
    """Weights that would not load: removed, so they are downloaded again, when the
    error says the file is broken; kept when it is the machine or the libraries."""
    if not bad_file(error):
        log.error(f"{what}.load_failed", path=path, error=str(error)[:300])
        return
    log.error(f"{what}.bad_weights", path=path, error=str(error)[:300])
    try:
        os.remove(path)
    except OSError:
        return
    _write_marker(path, removed_at=time.time())


def loaded(path: str) -> None:
    """The weights loaded: forget that an earlier copy was removed."""
    try:
        os.remove(_marker(path))
    except OSError:
        pass


def fetch_weights(url: str, path: str, *, timeout: float, what: str) -> str:
    """The weights file, downloaded first if it is not there.

    After a copy was removed for failing to load, a new one is downloaded at once,
    but not again within REDOWNLOAD_SECONDS if that one fails too.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return path
    last = _read_marker(path).get("downloaded_at")
    if last and time.time() - float(last) < REDOWNLOAD_SECONDS:
        after = datetime.fromtimestamp(float(last) + REDOWNLOAD_SECONDS).strftime("%d %b %H:%M")
        raise RuntimeError(f"its weights would not load and were removed; they are "
                           f"downloaded again after {after}")
    download(url, path, timeout=timeout, what=what)
    if os.path.exists(_marker(path)):
        _write_marker(path, downloaded_at=time.time())
    return path


def _weights_path() -> str:
    path = os.path.join(settings.models_root, _MODEL_FILE)
    return fetch_weights(_MODEL_URL, path, timeout=300, what="detector")


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
                loaded(path)
                log.info("detector.loaded")
    return _model


def load() -> None:
    """Load the model now (the AI pass does this once, before touching any photo)."""
    _get_model()


def detect(image_path: str, conf: float = DETECT_CONF) -> list[dict]:
    """Every box MegaDetector finds: [{category, confidence, bbox}], category 0 an
    animal, 1 a person, 2 a vehicle. People and vehicles used to be dropped here, so
    a walker or a truck at a stand was filed as an empty frame (audit F-25)."""
    model = _get_model()
    results = model.predict(image_path, device="cpu", verbose=False, conf=conf)
    out: list[dict] = []
    for r in results:
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            continue
        for i in range(len(boxes)):
            category = int(boxes.cls[i])
            if category in (ANIMAL_CATEGORY, PERSON_CATEGORY, VEHICLE_CATEGORY):
                out.append({
                    "category": category,
                    "confidence": float(boxes.conf[i]),
                    "bbox": [float(v) for v in boxes.xyxy[i]],
                })
    return out


def split(boxes: list[dict]) -> tuple[list[dict], float, float]:
    """(the animal boxes, the surest person, the surest vehicle) of detect()'s answer.

    A box with no category is an animal: the answer detect_animals gives, and boxes
    stored before people were looked for."""
    animals = [b for b in boxes if b.get("category", ANIMAL_CATEGORY) == ANIMAL_CATEGORY]
    person = max((b["confidence"] for b in boxes if b.get("category") == PERSON_CATEGORY),
                 default=0.0)
    vehicle = max((b["confidence"] for b in boxes if b.get("category") == VEHICLE_CATEGORY),
                  default=0.0)
    return animals, round(person, 4), round(vehicle, 4)


def detect_animals(image_path: str, conf: float = DETECT_CONF) -> list[dict]:
    """Return [{confidence, bbox}] for animal detections in the image."""
    return [{"confidence": b["confidence"], "bbox": b["bbox"]}
            for b in split(detect(image_path, conf))[0]]
