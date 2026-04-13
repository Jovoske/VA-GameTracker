"""VA GameTracker - Full sync & classify pipeline"""
import os
import sqlite3
from datetime import datetime
from backend.spypoint_sync import sync_all
from backend.classifier import classify_image
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

    # Step 2: Classify unprocessed sightings
    print("[2/3] Running AI classification (MegaDetector + SpeciesNet)...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Find sightings without classification
    unclassified = c.execute('''
        SELECT id, image_url, camera_id, timestamp
        FROM sightings WHERE category IS NULL AND image_url IS NOT NULL
    ''').fetchall()

    classified = 0
    for row in unclassified:
        image_path = row['image_url']
        if not image_path or not os.path.exists(image_path):
            continue

        results = classify_image(image_path)
        if results:
            best = max(results, key=lambda x: x.get('detection_confidence', 0))
            species = best.get('common_name', 'Unknown')
            boar_cat = best.get('boar_category')
            conf = best.get('species_confidence', best.get('detection_confidence', 0))

            # Use boar_category if it's a boar, otherwise use species name
            category = boar_cat if boar_cat else species

            c.execute('''UPDATE sightings
                SET category = ?, confidence = ?, notes = COALESCE(notes, '') || ?
                WHERE id = ?''',
                (category, conf,
                 f'\nSpecies: {species} ({conf:.0%})',
                 row['id']))
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
