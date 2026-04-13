"""VA GameTracker - Weather data from Open-Meteo API"""
import requests
from datetime import datetime, timedelta
import math

# Piedras Lisas, Alatoz coordinates
DEFAULT_LAT = 39.0947
DEFAULT_LON = -1.3608

MOON_PHASES = [
    'New Moon', 'Waxing Crescent', 'First Quarter', 'Waxing Gibbous',
    'Full Moon', 'Waning Gibbous', 'Last Quarter', 'Waning Crescent'
]

WIND_DIRECTIONS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def degrees_to_direction(degrees):
    """Convert wind degrees to compass direction."""
    idx = round(degrees / 22.5) % 16
    return WIND_DIRECTIONS[idx]


def get_moon_phase(date=None):
    """Calculate moon phase for a given date."""
    if date is None:
        date = datetime.now()
    if isinstance(date, str):
        date = datetime.fromisoformat(date.replace('Z', '+00:00'))

    # Synodic month calculation
    ref = datetime(2000, 1, 6, 18, 14)  # Known new moon
    diff = (date - ref).total_seconds()
    synodic = 29.53058867 * 86400
    phase = (diff % synodic) / synodic
    illumination = (1 - math.cos(2 * math.pi * phase)) / 2

    idx = int(phase * 8) % 8
    return {
        'phase': MOON_PHASES[idx],
        'illumination': round(illumination * 100, 1)
    }


def get_current_weather(lat=DEFAULT_LAT, lon=DEFAULT_LON):
    """Get current weather conditions from Open-Meteo."""
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            'latitude': lat,
            'longitude': lon,
            'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure',
            'timezone': 'Europe/Madrid'
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()['current']
        moon = get_moon_phase()

        return {
            'temperature': data['temperature_2m'],
            'humidity': data['relative_humidity_2m'],
            'wind_speed': data['wind_speed_10m'],
            'wind_direction': degrees_to_direction(data['wind_direction_10m']),
            'wind_degrees': data['wind_direction_10m'],
            'pressure': data['surface_pressure'],
            'moon_phase': moon['phase'],
            'moon_illumination': moon['illumination'],
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Weather API error: {e}")
        moon = get_moon_phase()
        return {
            'temperature': None,
            'humidity': None,
            'wind_speed': None,
            'wind_direction': None,
            'pressure': None,
            'moon_phase': moon['phase'],
            'moon_illumination': moon['illumination'],
            'timestamp': datetime.now().isoformat()
        }


def get_historical_weather(lat=DEFAULT_LAT, lon=DEFAULT_LON, date_str=None):
    """Get historical weather for a specific date."""
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            'latitude': lat,
            'longitude': lon,
            'start_date': date_str,
            'end_date': date_str,
            'hourly': 'temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure',
            'timezone': 'Europe/Madrid'
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Historical weather error: {e}")
        return None


def enrich_sighting_weather(timestamp, lat=DEFAULT_LAT, lon=DEFAULT_LON):
    """Get weather data for a specific sighting timestamp."""
    weather = get_current_weather(lat, lon)
    moon = get_moon_phase(datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp)
    weather['moon_phase'] = moon['phase']
    weather['moon_illumination'] = moon['illumination']
    return weather
