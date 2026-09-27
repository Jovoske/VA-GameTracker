"""One definition of "a photo worth showing" for every list in the app.

An animal photo is shown when it holds at least one sighting of a species that is
not hidden, or when the detector found an animal nobody has named yet. A photo of
nothing but hidden species (rabbits) is left out everywhere: the feed, the camera
gallery, the counts on Tonight, the alerts. Empty frames never show.

The same goes for what is counted: VISIBLE_SIGHTING is the test every forecast,
alert, insight and pattern query puts on a sighting, so a species hidden in
Settings, or a photo a hunter marked "nothing in it", never counts anywhere.
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

# The other half of it: a photo of nothing but hidden species, which no flag on the
# photo itself can bring back (only showing the animal again in Admin does).
ONLY_HIDDEN_SPECIES = and_(_HIDDEN_DETECTION, ~_VISIBLE_DETECTION)

# SQL predicate on a sighting: a Detection joined to its Image and its Species. It
# counts when its species is not hidden and nobody marked its photo "nothing in it"
# (the sighting row stays, so keeping the photo again brings it back).
VISIBLE_SIGHTING = and_(Species.hidden.is_(False), Image.is_empty_frame.isnot(True))
