"""VA GameTracker - Database initialization"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'gametracker.db')

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS cameras (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        latitude REAL,
        longitude REAL,
        altitude REAL,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS individuals (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN ('Big Boar', 'Sow', 'Juvenile', 'Piglet')),
        description TEXT,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        total_sightings INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sightings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT NOT NULL,
        individual_id TEXT,
        category TEXT,
        timestamp TIMESTAMP NOT NULL,
        temperature REAL,
        wind_direction TEXT,
        wind_speed REAL,
        humidity REAL,
        pressure REAL,
        moon_phase TEXT,
        moon_illumination REAL,
        confidence REAL,
        image_url TEXT,
        spypoint_photo_id TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (camera_id) REFERENCES cameras(id),
        FOREIGN KEY (individual_id) REFERENCES individuals(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS spypoint_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT,
        photos_synced INTEGER,
        last_photo_date TIMESTAMP,
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Insert default cameras for Piedras Lisas estate, Alatoz
    cameras = [
        ('PL14', 'PL14', 'South ridge trail', 39.0930, -1.3600, 858),
        ('PL15B', 'PL15B', 'Oak stand waterhole', 39.0945, -1.3615, 852),
        ('PL15D', 'PL15D', 'North creek crossing', 39.0960, -1.3590, 845),
        ('PL19', 'PL19', 'Cornfield edge feeder', 39.0920, -1.3580, 860),
    ]
    for cam in cameras:
        c.execute('INSERT OR IGNORE INTO cameras VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)', cam)

    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")

if __name__ == '__main__':
    init_db()
