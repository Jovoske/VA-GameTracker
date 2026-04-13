"""VA GameTracker - Full sync & classify pipeline"""
import os
import sqlite3
from datetime import datetime
from backend.spypoint_sync import sync_all
from backend.classifier import classify_from_url, classify_from_spypoint_tags
from backend.weather import enrich_sighting_weather
from backend.init_db import init_db, DB_PATH


def run_pipeline():
    """Full pipeline: sync photos → classify → enrich weather."""
    print(f"\n{'='*50}")
    print(f"VA GameTracker Pipeline - {datetime.now().isoformat()}")
    print(f"{'='*50}\n")

    # Ensure DB exists
    if not os.path.exists(DB_PATH):
        init_db()

    # Step 1: Sync new photos from SPYPOINT
    print("[1/3] Syncing SPYPOINT photos...")
    new_photos = sync_all()
    print(f"      {new_photos} new photos synced\n")

    # Step 2: Classify unprocessed sightings using iNaturalist API
    print("[2/3] Classifying species (iNaturalist Vision API)...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Find sightings without classification
    unclassified = c.execute('''
        SELECT id, image_url, camera_id, timestamp
        FROM sightings WHERE category IS NULL AND image_url IS NOT NULL
        LIMIT 50
    ''').fetchall()

    classified = 0
    for row in unclassified:
        image_url = row['image_url']

        # Try iNaturalist API if we have a CDN URL
        species = 'Unknown'
        confidence = 0.0

        if image_url and image_url.startswith('http'):
            species, confidence = classify_from_url(image_url)
            if species != 'Unknown':
                print(f"      #{row['id']}: {species} ({confidence:.0%})")

        if species == 'Unknown':
            # No classification available
            confidence = 0.0

        c.execute('''UPDATE sightings
            SET category = ?, confidence = ?
            WHERE id = ?''',
            (species, confidence, row['id']))
        classified += 1

    conn.commit()
    print(f"      {classified}/{len(unclassified)} images classified\n")

    # Step 3: Enrich with weather data
    print("[3/3] Enriching weather data...")
    no_weather = c.execute('''
        SELECT id, timestamp FROM sightings
        WHERE temperature IS NULL AND timestamp IS NOT NULL
        LIMIT 50
    ''').fetchall()

    enriched = 0
    for row in no_weather:
        try:
            weather = enrich_sighting_weather(row['timestamp'])
            c.execute('''UPDATE sightings SET
                temperature = ?, humidity = ?, wind_speed = ?,
                wind_direction = ?, pressure = ?,
                moon_phase = ?, moon_illumination = ?
                WHERE id = ?''',
                (weather.get('temperature'), weather.get('humidity'),
                 weather.get('wind_speed'), weather.get('wind_direction'),
                 weather.get('pressure'), weather.get('moon_phase'),
                 weather.get('moon_illumination'), row['id']))
            enriched += 1
        except Exception as e:
            print(f"      Weather error for sighting {row['id']}: {e}")

    conn.commit()
    conn.close()
    print(f"      {enriched}/{len(no_weather)} sightings enriched with weather\n")

    print(f"{'='*50}")
    print(f"Pipeline complete!")
    print(f"{'='*50}\n")


if __name__ == '__main__':
    run_pipeline()
