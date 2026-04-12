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


def get_spypoint_token():
    """Authenticate with SPYPOINT API."""
    username = os.getenv('SPYPOINT_USERNAME')
    password = os.getenv('SPYPOINT_PASSWORD')

    if not username or not password:
        print("Error: SPYPOINT_USERNAME and SPYPOINT_PASSWORD must be set in .env")
        return None

    try:
        resp = requests.post(f"{SPYPOINT_API}/user/login", json={
            'username': username,
            'password': password
        }, timeout=15)
        resp.raise_for_status()
        return resp.json().get('token')
    except Exception as e:
        print(f"SPYPOINT login error: {e}")
        # Try pyspypoint as fallback
        try:
            from pyspypoint import SpypointCamera
            cam = SpypointCamera(username, password)
            return cam
        except ImportError:
            print("Install pyspypoint: pip install pyspypoint")
        except Exception as e2:
            print(f"pyspypoint fallback error: {e2}")
        return None


def get_cameras(token):
    """List SPYPOINT cameras."""
    try:
        if hasattr(token, 'cameras'):
            # pyspypoint object
            return token.cameras()

        headers = {'Authorization': f'Bearer {token}'}
        resp = requests.get(f"{SPYPOINT_API}/camera", headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Get cameras error: {e}")
        return []


def get_photos(token, camera_id, limit=50):
    """Get recent photos from a camera."""
    try:
        if hasattr(token, 'photos'):
            return token.photos(camera_id, limit=limit)

        headers = {'Authorization': f'Bearer {token}'}
        resp = requests.get(f"{SPYPOINT_API}/photo", headers=headers,
                          params={'camera': camera_id, 'limit': limit}, timeout=15)
        resp.raise_for_status()
        return resp.json().get('photos', [])
    except Exception as e:
        print(f"Get photos error: {e}")
        return []


def download_photo(url, photo_id):
    """Download a photo to local storage."""
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


def sync_camera(token, camera_info, db_conn):
    """Sync photos from a single camera."""
    camera_id = camera_info.get('id') or camera_info.get('_id', '')
    camera_name = camera_info.get('name', camera_id)

    print(f"Syncing camera: {camera_name} ({camera_id})")
    photos = get_photos(token, camera_id)
    synced = 0
    c = db_conn.cursor()

    for photo in photos:
        photo_id = photo.get('id') or photo.get('_id', '')
        # Check if already synced
        c.execute('SELECT id FROM sightings WHERE spypoint_photo_id = ?', (photo_id,))
        if c.fetchone():
            continue

        # Download photo
        photo_url = photo.get('url') or photo.get('originUrl', '')
        if photo_url:
            local_path = download_photo(photo_url, photo_id)
        else:
            local_path = None

        # Extract timestamp
        ts = photo.get('date') or photo.get('createdAt', datetime.now().isoformat())

        # Map SPYPOINT camera name to our camera IDs
        mapped_camera = map_camera_name(camera_name)

        c.execute('''INSERT INTO sightings
            (camera_id, timestamp, image_url, spypoint_photo_id, notes)
            VALUES (?, ?, ?, ?, ?)''',
            (mapped_camera, ts, local_path or photo_url, photo_id,
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
