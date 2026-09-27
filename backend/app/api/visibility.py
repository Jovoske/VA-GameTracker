"""One definition of "a photo worth showing" for every list in the app.

An animal photo is shown when it holds at least one sighting of a species that is
not hidden, or when the detector found an animal nobody has named yet. A photo of
nothing but hidden species (rabbits) is left out everywhere: the feed, the camera
gallery, the counts on Tonight, the alerts. Empty frames never show.

The same goes for what is counted: VISIBLE_SIGHTING is the test every forecast,
alert, insight and pattern query puts on a sighting, so a species hidden in
Settings, or a photo a hunter marked "nothing in it", never counts anywhere.

A frame with a person or a vehicle in it (PEOPLE) is neither: it is out of every
shared list and every count, whatever else is in it, and only an admin sees it, in
Photos' "People & vehicles" (feature 25). A walker, a poacher or the keeper's truck
at a stand is estate business, not a sighting, and nobody's photo for the team feed.
"""
from sqlalchemy import and_, exists, func, or_

from app.models import Detection, Image, Species

# How sure MegaDetector must be (Image.person_conf, vehicle_conf) before a frame is
# one of people or vehicles. A person at a lower bar than a vehicle: a walker in the
# team's feed is the worse mistake, while a feeder or a rock read as a vehicle takes
# a camera's animals out of the lists. An admin can put a frame back (people_cleared).
PERSON_MIN = 0.2
VEHICLE_MIN = 0.4

_PERSON = func.coalesce(Image.person_conf, 0) >= PERSON_MIN
_VEHICLE = func.coalesce(Image.vehicle_conf, 0) >= VEHICLE_MIN

# SQL predicates on Image: a frame of people or vehicles, and one that is not. A frame
# the detector has not looked at for them yet (NULL) is not.
HAS_PERSON = and_(Image.people_cleared.is_(False), _PERSON)
HAS_VEHICLE = and_(Image.people_cleared.is_(False), _VEHICLE)
PEOPLE = and_(Image.people_cleared.is_(False), or_(_PERSON, _VEHICLE))
NO_PEOPLE = or_(Image.people_cleared.is_(True), and_(~_PERSON, ~_VEHICLE))


def people_in(image: Image) -> tuple[bool, bool]:
    """(a person, a vehicle) in this frame, as PEOPLE judges it."""
    if image.people_cleared:
        return False, False
    return ((image.person_conf or 0) >= PERSON_MIN, (image.vehicle_conf or 0) >= VEHICLE_MIN)


def is_people(image: Image) -> bool:
    """A frame of people or vehicles: an admin's photo, never the team's."""
    return any(people_in(image))


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
    NO_PEOPLE,
    or_(_VISIBLE_DETECTION, ~_HIDDEN_DETECTION),
)

# The other half of it: a photo of nothing but hidden species, which no flag on the
# photo itself can bring back (only showing the animal again in Admin does).
ONLY_HIDDEN_SPECIES = and_(_HIDDEN_DETECTION, ~_VISIBLE_DETECTION)

# SQL predicate on a sighting: a Detection joined to its Image and its Species. It
# counts when its species is not hidden, nobody marked its photo "nothing in it" (the
# sighting row stays, so keeping the photo again brings it back), and there is no
# person or vehicle in the frame (the dog on a walk is not wildlife, and never pushed).
VISIBLE_SIGHTING = and_(Species.hidden.is_(False), Image.is_empty_frame.isnot(True), NO_PEOPLE)

# SQL predicate on Image: a frame someone marked "nothing in it" or the detector found
# empty, that the team may see (Cameras' "Show empty photos"): not one of people.
SHOWN_EMPTY = and_(Image.is_empty_frame.is_(True), NO_PEOPLE)
