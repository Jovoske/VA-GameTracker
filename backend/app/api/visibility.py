"""One definition of "a photo worth showing" for every list in the app.

An animal photo is shown when it holds at least one sighting of a species that is
not hidden, or when the detector found an animal nobody has named yet. A photo of
nothing but hidden species (rabbits) is left out everywhere: the feed, the camera
gallery, the counts on Tonight, the alerts. Empty frames never show.
"""
from sqlalchemy import and_, exists, or_

from app.models import Detection, Image, Species

_VISIBLE_DETECTION = exists().where(
    Detection.image_id == Image.id,
    Detection.species_id == Species.id,
    Species.hidden.is_(False),
)
_HIDDEN_DETECTION = exists().where(
    Detection.image_id == Image.id,
    Detection.species_id == Species.id,
    Species.hidden.is_(True),
)

# SQL predicate on Image: an animal frame that is not only hidden species.
VISIBLE_ANIMAL = and_(
    Image.is_empty_frame.isnot(True),
    or_(_VISIBLE_DETECTION, ~_HIDDEN_DETECTION),
)
