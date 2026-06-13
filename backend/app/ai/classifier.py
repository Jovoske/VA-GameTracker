"""DeepFaune species classifier — DINOv2 ViT-Large on animal crops (CPU).

The class list is the DeepFaune v1.3 (v3 checkpoint) order, validated against
real estate frames (wild boar at index 32). Weights mirror from HuggingFace.
"""
from __future__ import annotations

import os
import threading

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_URL = (
    "https://huggingface.co/Addax-Data-Science/Deepfaune_v1.3/resolve/main/"
    "deepfaune-vit_large_patch14_dinov2.lvd142m.v3.pt"
)
_FILE = "deepfaune-vit_large_patch14_dinov2.lvd142m.v3.pt"
_BACKBONE = "vit_large_patch14_dinov2.lvd142m"
CROP_SIZE = 182

# DeepFaune v1.3 (v3) classes, in index order. Verified: boar=32, red deer=4, roe deer=8.
DEEPFAUNE_CLASSES = [
    "bison", "badger", "ibex", "beaver", "red deer", "chamois", "cat", "goat", "roe deer",
    "dog", "fallow deer", "squirrel", "moose", "equid", "genet", "wolverine", "hedgehog",
    "lagomorph", "wolf", "otter", "lynx", "marmot", "micromammal", "mouflon", "sheep",
    "mustelid", "bird", "bear", "nutria", "raccoon", "fox", "reindeer", "wild boar", "cow",
]


def species_key(name: str) -> str:
    return name.replace(" ", "_")


def common_name(name: str) -> str:
    return name.title()


_model = None
_mean = None
_std = None
_lock = threading.Lock()


def _weights_path() -> str:
    os.makedirs(settings.models_root, exist_ok=True)
    path = os.path.join(settings.models_root, _FILE)
    if not os.path.exists(path):
        log.info("classifier.downloading", url=_URL)
        with httpx.stream("GET", _URL, follow_redirects=True, timeout=900) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        log.info("classifier.downloaded", bytes=os.path.getsize(path))
    return path


def _strip(key: str) -> str:
    for p in ("base_model.", "model.", "module."):
        if key.startswith(p):
            return key[len(p):]
    return key


def _get_model():
    global _model, _mean, _std
    if _model is None:
        with _lock:
            if _model is None:
                import timm
                import torch

                ckpt = torch.load(_weights_path(), map_location="cpu", weights_only=False)
                state = ckpt.get("state_dict", ckpt) if isinstance(ckpt, dict) else ckpt
                model = timm.create_model(
                    _BACKBONE, pretrained=False,
                    num_classes=len(DEEPFAUNE_CLASSES), dynamic_img_size=True,
                )
                model.load_state_dict({_strip(k): v for k, v in state.items()}, strict=False)
                model.eval()
                _model = model
                _mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
                _std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
                log.info("classifier.loaded", classes=len(DEEPFAUNE_CLASSES))
    return _model


def classify_crop(image_path: str, bbox: list[float] | None) -> tuple[str, str, float] | None:
    """Return (species_key, common_name, confidence) for the animal crop, or None."""
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image as PILImage

    model = _get_model()
    img = PILImage.open(image_path).convert("RGB")
    if bbox:
        img = img.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
    img = img.resize((CROP_SIZE, CROP_SIZE))
    t = torch.from_numpy(np.array(img)).permute(2, 0, 1).float() / 255.0
    t = (t - _mean) / _std
    with torch.no_grad():
        probs = F.softmax(model(t.unsqueeze(0)), dim=1)[0]
    idx = int(torch.argmax(probs))
    name = DEEPFAUNE_CLASSES[idx]
    return species_key(name), common_name(name), round(float(probs[idx]), 4)
