"""detections: a hunter's fix of the species; species: names a hunter uses

Revision ID: 0025_species_fixes
Revises: 0024_camera_retired
Create Date: 2026-09-27

- detections.corrected_at / corrected_by: a hunter said what the animal is from the
  photo viewer. The species is theirs from then on and the AI never changes it back.
  corrected_by is the login that fixed it (SET NULL when that login is removed: the
  fix stays, the name goes).
- The species names the classifier gave (DeepFaune's, in title case: "Wild Boar",
  "Micromammal", "Mustelid", "Equid", and "Rabbit" for hares and rabbits together)
  become the names the app starts with now (ai.classifier.common_name): "Wild boar",
  "Mouse or rat", "Marten or weasel", "Horse or donkey", "Hare or rabbit". Only a name
  still exactly as the classifier wrote it changes, so a name somebody chose stays.
  Whether a species is hidden or in the advice goes with its key, not its name, so
  hidden rabbits stay hidden as "Hare or rabbit".

A no-op on fresh installs, where 0001's create_all() builds the columns from the
models and there are no species yet.
"""
from sqlalchemy import text

from alembic import op

revision = "0025_species_fixes"
down_revision = "0024_camera_retired"
branch_labels = None
depends_on = None

# The DeepFaune v1.3 classes, as the classifier named them before (title case, with
# "Rabbit" for lagomorph) and as it names them now. Written out here, not imported:
# a migration must keep meaning what it meant when it ran.
_CLASSES = [
    "bison", "badger", "ibex", "beaver", "red deer", "chamois", "cat", "goat", "roe deer",
    "dog", "fallow deer", "squirrel", "moose", "equid", "genet", "wolverine", "hedgehog",
    "lagomorph", "wolf", "otter", "lynx", "marmot", "micromammal", "mouflon", "sheep",
    "mustelid", "bird", "bear", "nutria", "raccoon", "fox", "reindeer", "wild boar", "cow",
]
_READABLE = {
    "lagomorph": "Hare or rabbit",
    "micromammal": "Mouse or rat",
    "mustelid": "Marten or weasel",
    "equid": "Horse or donkey",
}


def _renames() -> list[tuple[str, str, str]]:
    """(species key, old name, new name) for every class whose name changes."""
    out = []
    for name in _CLASSES:
        old = "Rabbit" if name == "lagomorph" else name.title()
        new = _READABLE.get(name, name[:1].upper() + name[1:])
        if old != new:
            out.append((name.replace(" ", "_"), old, new))
    return out


def upgrade() -> None:
    op.execute(
        "ALTER TABLE detections ADD COLUMN IF NOT EXISTS corrected_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE detections ADD COLUMN IF NOT EXISTS corrected_by UUID "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    rename = text("UPDATE species SET common_name = :new WHERE id = :key AND common_name = :old")
    for key, old, new in _renames():
        op.get_bind().execute(rename, {"key": key, "old": old, "new": new})


def downgrade() -> None:
    # Hunters' fixes stay as species on their sightings; only who and when go.
    op.execute("ALTER TABLE detections DROP COLUMN IF EXISTS corrected_by")
    op.execute("ALTER TABLE detections DROP COLUMN IF EXISTS corrected_at")
    rename = text("UPDATE species SET common_name = :old WHERE id = :key AND common_name = :new")
    for key, old, new in _renames():
        op.get_bind().execute(rename, {"key": key, "old": old, "new": new})
