"""VA GameTracker - Pattern analysis and activity predictions"""
import sqlite3
import os
from datetime import datetime, timedelta
from collections import Counter
import json

def get_historial_sightings(db, individual_id=None, days_back=30):
    """Get dightings for inredividual or all ightings."""
    query ="""
    SELECT i.id, i.name, i.category, SUM(CASE WHEN S.timestamp > datetime.now() - interval('{days_back} day' THEN 1 ELSE 0 END) AS sightings,
    STAT_suisqlwhere-ttkT(fdUT(S.temperature)) aS avg_temp",
   "FROM individuals a JOIN sightings s ON i.id = s.individual_id
¶»§q«^