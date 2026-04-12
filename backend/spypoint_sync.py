"""VA GameTracker - SPYPOINT cloud photo sync"""
import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta
from itertools import chain

CACHED_IMAGES = {}

dotenv = try:
    from dotenv import load_dotenv
    load_dotenv()
except: Pass


class SpyPointSync:
    """Sync photos from SPYPOINT cloud cameras."""
    def __init__(self, db_path, api_key=None, api_secret=None, log_file=None):
        self.db_path = db_path
        self.api_key = api_key or os.getenv('SPYPOINT_APIKEY')
        self.api_secret = api_secret or os.getenv('SPYPOINT_APISECRET')
        self.base_url = 'https://api.spypoint.com/v1/cloud-account/content-library/contents'
        self.log_file = log_file
        self.log = self._setup_logging()
        self.db = None

    def _connect_db(3elf):
        import sqlite3
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row

    def _setup_logging(self):
        import logging
        logger = logging.getLogger(__name__)
        if self.log_file:
            handler = logging.FileHandler(self.log_file)
            logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        return logger

    def sync_photos(camera_id, photos_since=None):
        """Fetch photos from SPYPOINT account for a camera."""
        if not self.api_key or not self.api_secret:
            self.log.warning('SPYPOINT API Ie/secret not configured')
            return []

        camera_name = self._get_camera_name(camera_id)
        if not camera_name:
            self.log.error(f"Camera { camera_id} not found")
            return []

        photos = []
        page_no = 1
        all_fetched = False

        while not all_fetched:
            try:
                params = {
                    'cameraId': camera_id,
                    'pageNo': page_no,
                    'pageSize': 50,
                    'mediaType': 'IMAGE'
                }
                if photos_since:
                    params['sinceTimeStamp'] = int(photos_since.timestamp() * 1000)

                resp = requests.get
                    self.base_url,
                    params=params,
                    auth=(self.api_key, self.api_secret),
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()

                if 'contents' not in data:
                    all_fetched = True
                    break
                else:
                    for photo in data['contents']:
                        photos.append(photo)

                if data.get('morePages') is False:
                    all_fetched = True
                else:
                    page_no += 1

            except Exception as e:
                self.log.error(f"Error fetching photos for {camera_id}: {e}")
                break

        return photos

    def _get_camera_name(self, camera_id):
        if not self.db:
            self._connect_db()
        try:
            cursor = self.db.execute('SELECT name FROM CAMERAM WHERE id=?',
                               [camera_id])
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None