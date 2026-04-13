"""VA GameTracker - SPYPOINT cloud photo sync"""
import os
import sys
import sqlite3
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'gametracker.db')
IMAGE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'images')

SPYPOINT_API = "https://restapi.spypoint.com/api/v3"
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}


def get_spypoint_token():
    """Authenticate with SPYPOINT API."""
    username = os.getenv('SPYPOINT_USERNAME')
    password = os.getenv('SPYPOINT_PASSWORD')

    if not username or not password:
        print("Error: SPYPOINT_USERNAME and SPYPOINT_PASSWORD must be set")
        return None

    try:
        resp = requests.post(f"{SPYPOINT_API}/user/login",
                             json={'username': username, 'password': password},
                             headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json().get('token')
    except Exception as e:
        print(f"SPYPOINT login error: {e}")
        return None


def auth_headers(token):
    """Build authenticated request headers."""
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }


def get_cameras(token):
    """List SPYPOINT cameras."""
    try:
        resp = requests.get(f"{SPYPOINT_API}/camera/all",
                            headers=auth_headers(token), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Get cameras error: {e}")
        return []


def get_photos(token, camera_id, limit=50):
    """Get recent photos from a camera."""
    try:
        resp = requests.post(f"{SPYPOINT_API}/photo/all",
                             headers=auth_headers(token),
                             json={
                                 'camera': [camera_id],
                                 'dateEnd': '2100-01-01T00:00:00.000Z',
                                 'favorite': False,
                                 'hd': False,
                                 'limit': limit
                             },
                             timeout=15)
        resp.raise_for_status()
        return resp.json().get('photos', [])
    except Exception as e:
        print(f"Get photos error: {e}")
        return []


def photo_url(photo):
    """Build full photo URL from host/path response."""
    large = photo.get('large', {})
    if large.get('host') and large.get('path'):
        return f"https://{large['host']}/{large['path']}"
    small = photo.get('small', {})
    if small.get('host') and small.get('path'):
        return f"https://{small['host']}/{small['path']}"
    # Fallback to direct url fields
    return photo.get('url') or photo.get('originUrl', '')


def download_photo(url, photo_id):
    """Download a photo to local storage."""
    if not url:
        return None
    os.makedirs(IMAGE_DIR, exist_ok=True)
    filepath = os.path.join(IMAGE_DIR, f"{photo_id}.jpg")
    if os.path.exists(filepath):
        return filepath

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(resp.content)
        return filepath
    except Exception as e:
        print(f"Download error for {photo_id}: {e}")
        return None


def ensure_camera_exists(db_conn, camera_id, camera_name):
    """Auto-create camera entry if it doesn't exist."""
    c = db_conn.cursor()
    c.execute('SELECT id FROM cameras WHERE id = ?', (camera_id,))
    if not c.fetchone():
        c.execute('INSERT OR IGNORE INTO cameras (id, name, description, active) VALUES (?, ?, ?, 1)',
                  (camera_id, camera_name, f'SPYPOINT camera {camera_name}'))
        db_conn.commit()
        print(f"  Auto-created camera entry: {camera_name} ({camera_id})")


def sync_camera(token, camera_info, db_conn):
    """Sync photos from a single camera."""
    camera_id = camera_info.get('id') or camera_info.get('_id', '')
    # Try to get human-readable name from config or top-level name
    config = camera_info.get('config', {})
    camera_name = config.get('name') or camera_info.get('name', camera_id)
    print(f"  Camera info keys: {list(camera_info.keys())}")
    print(f"  Camera name resolved: {camera_name} (id: {camera_id})")

    # Ensure this camera exists in our DB
    ensure_camera_exists(db_conn, camera_id, camera_name)

    print(f"Syncing camera: {camera_name} ({camera_id})")
    photos = get_photos(token, camera_id)
    synced = 0
    c = db_conn.cursor()

    for photo in photos:
        pid = photo.get('id') or photo.get('_id', '')
        # Check if already synced
        c.execute('SELECT id FROM sightings WHERE spypoint_photo_id = ?', (pid,))
        if c.fetchone():
            continue

        # Get CDN URL (don't download — ephemeral storage)
        url = photo_url(photo)

        # Extract timestamp
        ts = photo.get('date') or photo.get('createdAt', datetime.now().isoformat())

        # Store with Spypoint camera ID and CDN URL
        c.execute('''INSERT INTO sightings
            (camera_id, timestamp, image_url, spypoint_photo_id, notes)
            VALUES (?, ?, ?, ?, ?)''',
            (camera_id, ts, url, pid,
             f"Auto-synced from SPYPOINT {camera_name}"))

        synced += 1

    # Log sync
    c.execute('''INSERT INTO spypoint_sync_log (camera_id, photos_synced, synced_at)
        VALUES (?, ?, ?)''', (camera_id, synced, datetime.now().isoformat()))

    db_conn.commit()
    print(f"  Synced {synced} new photos from {camera_name}")
    return synced


def map_camera_name(spypoint_name):
    """Map SPYPOINT camera names to local camera IDs."""
    name_upper = spypoint_name.upper()
    if 'PL14' in name_upper:
        return 'PL14'
    elif 'PL15B' in name_upper:
        return 'PL15B'
    elif 'PL15D' in name_upper:
        return 'PL15D'
    elif 'PL19' in name_upper:
        return 'PL19'
    return spypoint_name


def sync_all():
    """Sync all SPYPOINT cameras."""
    print("=== VA GameTracker - SPYPOINT Sync ===")
    print(f"Time: {datetime.now().isoformat()}")

    token = get_spypoint_token()
    if not token:
        print("Failed to authenticate with SPYPOINT")
        return 0

    cameras = get_cameras(token)
    if not cameras:
        print("No cameras found")
        return 0

    conn = sqlite3.connect(DB_PATH)
    total = 0
    for cam in cameras:
        total += sync_camera(token, cam, conn)

    conn.close()
    print(f"Total: {total} new photos synced")
    return total


if __name__ == '__main__':
    sync_all()
