"""Made-up estate data for the UI tests and for trying the app on a laptop.

    cd backend
    alembic upgrade head && python -m app.seed && python scripts/demo_data.py

Four cameras (one out of photo credits, one on a low battery, one gone quiet), four
stands, a bedding area, 45 nights of photos in bursts with the animals named, a fixed
"last night" at PL19 Charca and a replay across three cameras, and a member and a
viewer beside the seed's admin (member@ / viewer@gamesense.local, password
"changeme"). The photos are a dozen drawn JPEGs under MEDIA_ROOT. Run it once, on a
database with no photos yet: it adds nothing twice. Never on the real server.
"""
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image as PImage  # noqa: E402
from PIL import ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import media  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.forecasting.exposure import recompute_camera_nights  # noqa: E402
from app.models import (  # noqa: E402
    Camera,
    Detection,
    Estate,
    Image,
    Notification,
    Species,
    Stand,
    SyncLog,
    User,
    Zone,
)

random.seed(42)
TZ = ZoneInfo("Europe/Madrid")
MEDIA = settings.media_root
os.makedirs(MEDIA, exist_ok=True)

# a handful of JPEGs, stored as the importers store them: under MEDIA_ROOT
files = []
for i in range(12):
    p = os.path.join(MEDIA, f"syn_{i}.jpg")
    if not os.path.exists(p):
        # Night IR look: grey ground, a lighter clearing, dark trees and an "animal".
        g = 60 + i * 8
        im = PImage.new("RGB", (1280, 720), (g, g, g - 6))
        d = ImageDraw.Draw(im)
        d.ellipse([200 - i * 10, 380, 1180 - i * 10, 820], fill=(g + 40, g + 40, g + 34))
        for t in range(5):
            x = (i * 137 + t * 263) % 1200
            d.rectangle([x, 0, x + 36 + t * 6, 460], fill=(g - 40, g - 40, g - 44))
        ax = 300 + (i * 71) % 600
        d.ellipse([ax, 430, ax + 260, 560], fill=(30 + i * 4, 30 + i * 4, 28))
        d.ellipse([ax + 220, 440, ax + 320, 510], fill=(30 + i * 4, 30 + i * 4, 28))
        d.text((40, 680), f"SYNTH {i}  19C", fill=(230, 230, 230))
        im.save(p, quality=80)
    files.append(media.stored(p))

SPECIES = [
    ("wild_boar", "Wild Boar", True, True), ("red_deer", "Red Deer", True, True),
    ("roe_deer", "Roe Deer", True, True), ("fallow_deer", "Fallow Deer", True, True),
    ("fox", "Fox", True, True), ("badger", "Badger", True, True),
    ("lagomorph", "Rabbit", False, True), ("bird", "Bird", False, False),
]
MIX = [("wild_boar", 0.35), ("red_deer", 0.2), ("roe_deer", 0.12), ("fallow_deer", 0.05),
       ("fox", 0.12), ("badger", 0.05), ("lagomorph", 0.08), ("bird", 0.03)]
# name, spypoint_id, lat, lon, reported hours ago, photos used, photo limit, battery
CAMERAS = [
    ("PL19 Charca", "sp-001", 39.0951, -1.3622, 2, 400, 1000, 85),
    ("Barranco Norte", "sp-002", 39.0990, -1.3580, 5, 1000, 1000, 60),  # out of credits
    ("Encinar del Pozo", None, 39.0921, -1.3651, 3, None, None, 15),     # low battery (UBox)
    ("Pinar Alto", "sp-004", 39.1010, -1.3700, 80, 200, 1000, 40),        # gone quiet
]
BEDDING = {"type": "Polygon", "coordinates": [[
    [-1.366, 39.096], [-1.362, 39.097], [-1.361, 39.094], [-1.365, 39.093], [-1.366, 39.096]]]}
now = datetime.now(UTC)


def pick() -> str:
    r, acc = random.random(), 0.0
    for species, weight in MIX:
        acc += weight
        if r <= acc:
            return species
    return "wild_boar"


def burst(db, cam, when, species, group_type, size, ids=None, step=0):
    """Three frames of one visit, the animal named on each."""
    for b in range(3):
        img = Image(camera_id=cam.id, captured_at=when + timedelta(seconds=b * step),
                    original_path=random.choice(files) if ids is None else files[ids[b]],
                    spypoint_photo_id=None, is_empty_frame=False, animal_conf=0.9,
                    processed_at=when + timedelta(minutes=30), width=1280, height=720,
                    created_at=min(now, when + timedelta(minutes=25)))
        db.add(img)
        db.flush()
        db.add(Detection(image_id=img.id, species_id=species, species_conf=0.94,
                         sex="unknown", group_size=size, group_type=group_type))
        yield img


with SessionLocal() as db:
    estate = db.scalar(select(Estate))
    for sid, name, prio, hunt in SPECIES:
        if db.get(Species, sid) is None:
            db.add(Species(id=sid, common_name=name, is_priority=prio, huntable=hunt))
    db.flush()
    admin = db.scalar(select(User).where(User.role == "admin"))
    for email, role in [("member@gamesense.local", "member"), ("viewer@gamesense.local", "viewer")]:
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(estate_id=estate.id, email=email, password_hash=hash_password("changeme"),
                        role=role))
    cams = []
    for name, spid, lat, lon, rep, cnt, lim, bat in CAMERAS:
        c = db.scalar(select(Camera).where(Camera.name == name))
        if c is None:
            c = Camera(estate_id=estate.id, name=name, provider_name=name, spypoint_id=spid,
                       ubox_uid=None if spid else "ubox-777", lat=lat, lon=lon,
                       model="FLEX" if spid else "UBox Pro", battery_pct=bat, signal_pct=70,
                       last_report_at=now - timedelta(hours=rep),
                       last_sync_at=now - timedelta(minutes=20), photo_count=cnt,
                       photo_limit=lim, plan_name="Basic" if spid else None,
                       cycle_end=now + timedelta(days=9) if spid else None,
                       sd_used_mb=3000, sd_total_mb=32000)
            db.add(c)
        cams.append(c)
    db.flush()

    stands = [("Charca stand", cams[0], 39.0953, -1.3618, [200, 260], [30, 60]),
              ("Barranco high seat", cams[1], 39.0985, -1.3585, [90, 150], [300, 330]),
              ("Encinar tower", cams[2], 39.0925, -1.3645, [0, 45], None),
              ("Loma sin sitio", None, None, None, None, None)]
    for name, cam, lat, lon, shoot, appr in stands:
        if db.scalar(select(Stand).where(Stand.name == name)) is None:
            db.add(Stand(estate_id=estate.id, camera_id=cam.id if cam else None, name=name,
                         lat=lat, lon=lon, shooting_dirs_deg=shoot, approach_dirs_deg=appr))
    if db.scalar(select(Zone)) is None:
        db.add(Zone(estate_id=estate.id, kind="bedding", name="Monte bajo", polygon=BEDDING))
    db.flush()

    # 45 nights up to now, a few visits a night, in bursts of three frames
    if db.scalar(select(Image).limit(1)) is None:
        n_img = 0
        for ci, cam in enumerate(cams):
            last_day = 3 if ci == 3 else 0  # the quiet camera stopped 3 days ago
            for back in range(45, last_day - 1, -1):
                day = (now.astimezone(TZ) - timedelta(days=back)).date()
                for _ in range(random.randint(1, 6)):
                    hour = random.choice([19, 20, 21, 22, 22, 23, 23, 0, 1, 2, 4, 6, 7, 8])
                    base = datetime(day.year, day.month, day.day, hour, random.randint(0, 59),
                                    random.randint(0, 59), tzinfo=TZ)
                    if hour < 12:
                        base += timedelta(days=1)
                    if base > now:
                        continue
                    species = pick()
                    group = {"wild_boar": [None, "sounder", "sow_with_piglets"],
                             "red_deer": [None, "herd", "hind_with_calf"]}.get(species, [None])
                    n_img += len(list(burst(db, cam, base, species, random.choice(group),
                                            random.randint(1, 6))))
                    for _ in range(random.randint(0, 3)):  # empty frames
                        t = base + timedelta(minutes=random.randint(5, 120))
                        if t <= now:
                            db.add(Image(camera_id=cam.id, captured_at=t,
                                         original_path=random.choice(files), is_empty_frame=True,
                                         animal_conf=0.05, processed_at=t + timedelta(minutes=30),
                                         created_at=min(now, t + timedelta(minutes=20))))
        print("animal images", n_img)

    # Last night at PL19 Charca, fixed so the map's camera sheet has something known to
    # show: a sounder twice (two visits of three frames) and a hind once. Then across
    # cameras, for the replay: a sounder at Encinar at 20:50 before Charca at 21:40, a
    # hind and calf at Barranco at 00:30 before Charca at 02:15, a fox at Encinar at dawn.
    if db.scalar(select(Image).where(Image.spypoint_photo_id.like("demo-%")).limit(1)) is None:
        evening = (now.astimezone(TZ) - timedelta(hours=6)).date() - timedelta(days=1)

        def at(day_off, h, m, s=12):
            d = evening + timedelta(days=day_off)
            return datetime(d.year, d.month, d.day, h, m, s, tzinfo=TZ)

        visits = [(cams[0], at(0, 21, 40), "wild_boar", "sounder", 4, 0, "demo-0"),
                  (cams[0], at(0, 23, 10), "wild_boar", "sounder", 4, 0, "demo-1"),
                  (cams[0], at(1, 2, 15), "red_deer", "hind_with_calf", 2, 0, "demo-2"),
                  (cams[2], at(0, 20, 50, 30), "wild_boar", "sounder", 4, 20, "replay-0"),
                  (cams[1], at(1, 0, 30, 30), "red_deer", "hind_with_calf", 2, 20, "replay-1"),
                  (cams[2], at(1, 4, 30, 30), "fox", None, 1, 20, "replay-2")]
        for k, (cam, when, species, group, size, step, tag) in enumerate(visits):
            ids = [(k * 3 + b) % len(files) for b in range(3)]
            for b, img in enumerate(burst(db, cam, when, species, group, size, ids, step)):
                img.spypoint_photo_id = f"{tag}-{b}"
    db.add(SyncLog(status="ok", started_at=now - timedelta(minutes=20),
                   finished_at=now - timedelta(minutes=19), images_downloaded=12,
                   details={"provider": "pipeline", "results": {}}))
    for i in range(5):
        db.add(Notification(user_id=admin.id, kind="sighting", title="Wild Boar at PL19 Charca",
                            body="3 photos", url="/photos?species=wild_boar",
                            species_id="wild_boar", push_status="no_subscription",
                            created_at=now - timedelta(hours=i * 7)))
    db.commit()
    print(recompute_camera_nights(db))
    print("images", db.query(Image).count(), "detections", db.query(Detection).count())
