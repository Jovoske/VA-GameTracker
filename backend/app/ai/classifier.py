"""DeepFaune species classifier — DINOv2 ViT-Large on animal crops (CPU).

The class list is the DeepFaune v1.3 (v3 checkpoint) order, validated against
real estate frames (wild boar at index 32). Weights mirror from HuggingFace.

The same backbone also yields a 1024-dim pre-logits embedding per crop
(`embed_crop`), which the re-ID clustering uses to group sightings into
candidate individuals.
"""
from __future__ import annotations

import os
import threading

from app.ai.detector import WeightsMismatch, discard, fetch_weights, loaded
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


# The classes that can turn up at Alatoz. DeepFaune is trained on all of Europe, and
# took its top guess whatever it was, so Spanish night frames came back as moose,
# bison or reindeer. The rest can't be here: bison, beaver, chamois (Pyrenees and
# Cantabria only), moose, wolverine, marmot, bear, nutria, raccoon, reindeer and wolf.
ESTATE_CLASSES = frozenset({
    "badger", "ibex", "red deer", "cat", "goat", "roe deer", "dog", "fallow deer",
    "squirrel", "equid", "genet", "hedgehog", "lagomorph", "otter", "lynx",
    "micromammal", "mouflon", "sheep", "mustelid", "bird", "fox", "wild boar", "cow",
})
ESTATE_KEYS = frozenset(species_key(n) for n in ESTATE_CLASSES)


# DeepFaune's "lagomorph" is the taxonomic order (rabbits + hares); on this estate it is
# shown simply as "Rabbit". Keep the model class / species key as "lagomorph"; only the
# human-facing name is overridden.
_NAME_OVERRIDES = {"lagomorph": "Rabbit"}


def common_name(name: str) -> str:
    return _NAME_OVERRIDES.get(name, name.title())


_model = None
_mean = None
_std = None
_lock = threading.Lock()


def _weights_path() -> str:
    return fetch_weights(_URL, os.path.join(settings.models_root, _FILE),
                         timeout=900, what="classifier")


def _strip(key: str) -> str:
    for p in ("base_model.", "model.", "module."):
        if key.startswith(p):
            return key[len(p):]
    return key


def _load_weights(torch, model, path: str) -> None:
    """Put the checkpoint's weights in the model, refusing a file that doesn't fit it.

    Plain tensors only where the file allows it (then no code runs while it is read).
    A file missing the classifier head used to load "fine" with strict=False and name
    every animal at random; now it fails, is removed, and is fetched again next run
    (detector.discard, which keeps the file when the machine is the problem).
    """
    try:
        ckpt = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as e:  # a checkpoint that pickles more than tensors and numbers
        log.warning("classifier.weights_not_plain", error=str(e)[:200])
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
    state = ckpt.get("state_dict", ckpt) if isinstance(ckpt, dict) else ckpt
    report = model.load_state_dict({_strip(k): v for k, v in state.items()}, strict=False)
    missing = list(report.missing_keys)
    if any(k.startswith("head.") for k in missing) or len(missing) > 10:
        raise WeightsMismatch(f"checkpoint does not fit the model: {len(missing)} weights "
                              f"missing, e.g. {', '.join(missing[:3])}")


def _get_model():
    global _model, _mean, _std
    if _model is None:
        with _lock:
            if _model is None:
                import timm
                import torch

                path = _weights_path()
                model = timm.create_model(
                    _BACKBONE, pretrained=False,
                    num_classes=len(DEEPFAUNE_CLASSES), dynamic_img_size=True,
                )
                try:
                    _load_weights(torch, model, path)
                except Exception as e:
                    discard(path, "classifier", e)
                    raise
                loaded(path)
                model.eval()
                _model = model
                _mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
                _std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
                log.info("classifier.loaded", classes=len(DEEPFAUNE_CLASSES))
    return _model


def load() -> None:
    """Load the model now (the AI pass does this once, before touching any photo)."""
    _get_model()


def square(bbox: list[float]) -> tuple[int, int, int, int]:
    """The square around a box, centred on it (side = its longer edge).

    DeepFaune was trained on square crops; squashing a long side-on boar into a square
    distorted every crop. Where the square runs past the frame, PIL pads it with black.
    """
    x1, y1, x2, y2 = bbox
    side = max(x2 - x1, y2 - y1)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))


def _input_tensor(image_path: str, bbox: list[float] | None):
    """Square crop → 182px → ImageNet-normalized [1,3,H,W] tensor (classify + embed)."""
    import numpy as np
    import torch
    from PIL import Image as PILImage

    _get_model()  # ensures _mean / _std are populated
    img = PILImage.open(image_path).convert("RGB")
    if bbox:
        img = img.crop(square(bbox))
    img = img.resize((CROP_SIZE, CROP_SIZE))
    t = torch.from_numpy(np.array(img)).permute(2, 0, 1).float() / 255.0
    return ((t - _mean) / _std).unsqueeze(0)


def _best_allowed(probs) -> tuple[str, str, float]:
    """The likeliest class that can be on this estate, with its own probability (not
    renormalised: a frame split between "moose" and "red deer" stays unsure)."""
    values = probs.tolist() if hasattr(probs, "tolist") else list(probs)
    idx = max((i for i, n in enumerate(DEEPFAUNE_CLASSES) if n in ESTATE_CLASSES),
              key=values.__getitem__)
    name = DEEPFAUNE_CLASSES[idx]
    return species_key(name), common_name(name), round(float(values[idx]), 4)


def classify_crop(image_path: str, bbox: list[float] | None) -> tuple[str, str, float] | None:
    """Return (species_key, common_name, confidence) for the animal crop, or None."""
    import torch
    import torch.nn.functional as F

    model = _get_model()
    t = _input_tensor(image_path, bbox)
    with torch.no_grad():
        probs = F.softmax(model(t), dim=1)[0]
    return _best_allowed(probs)


def classify_and_embed(
    image_path: str, bbox: list[float] | None,
) -> tuple[tuple[str, str, float], list[float]]:
    """classify_crop and embed_crop from one pass through the backbone: the species
    pass stores the embedding "Look for repeats" needs at no extra cost."""
    import torch
    import torch.nn.functional as F

    model = _get_model()
    t = _input_tensor(image_path, bbox)
    with torch.no_grad():
        feats = model.forward_features(t)
        probs = F.softmax(model.forward_head(feats), dim=1)[0]
        emb = F.normalize(model.forward_head(feats, pre_logits=True)[0], dim=0)
    return _best_allowed(probs), emb.tolist()


def embed_crop(image_path: str, bbox: list[float] | None) -> list[float]:
    """1024-dim L2-normalized DINOv2 embedding of the crop (cosine-ready, for re-ID)."""
    import torch
    import torch.nn.functional as F

    model = _get_model()
    t = _input_tensor(image_path, bbox)
    with torch.no_grad():
        feats = model.forward_features(t)
        pooled = model.forward_head(feats, pre_logits=True)[0]  # pre-classifier features
        emb = F.normalize(pooled, dim=0)
    return emb.tolist()
