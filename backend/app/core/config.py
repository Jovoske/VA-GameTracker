"""Application configuration, loaded from environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database / cache
    database_url: str = "postgresql+psycopg://gamesense:gamesense@localhost:5432/gamesense"
    redis_url: str = "redis://localhost:6379/0"

    # Security
    jwt_secret: str = "dev-secret-change-me"
    # Key for saved camera-login passwords. Unset, JWT_SECRET is used. Set it (and let
    # one fetch run) before changing JWT_SECRET, or put the old JWT_SECRET in
    # PREVIOUS_JWT_SECRET, and saved logins keep working (app.core.crypto).
    credentials_key: str = ""
    previous_jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 43200  # 30 days — a field app shouldn't log you out weekly
    # "development" lets serve.py start with the secrets published in this repo
    # (app.core.startup). Anything else, including unset, is treated as the real server.
    app_env: str = "production"
    # Peers whose CF-Connecting-IP header is believed: the Cloudflare tunnel, which on
    # Db01 connects from this machine. Anyone else could write any address there.
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]
    # The interactive API docs (/docs, /redoc, /openapi.json) are off unless this is
    # set: on the public address they were a map of every endpoint to probe (K-12).
    enable_api_docs: bool = False

    # Initial admin + estate (seeded on first start)
    admin_email: str = "admin@gamesense.local"
    admin_password: str = "changeme"
    estate_name: str = "Piedras Lisas"
    estate_timezone: str = "Europe/Madrid"
    estate_lat: float = 39.0947
    estate_lon: float = -1.3608

    # SPYPOINT (Milestone 1)
    spypoint_username: str = ""
    spypoint_password: str = ""
    # Optional override; otherwise read the public Nordic web app's client setting.
    nordic_client_secret: str = ""
    sync_interval_minutes: int = 15

    # Where the Suntek FTP/email importer keeps its spool (ready/, failed/ ...), for the
    # counts on the admin status. Unset: <data>/ftp-spool beside the models folder.
    ftp_spool_root: str = ""

    # Notifications (Web Push). The VAPID key pair is generated on first use and kept
    # in the database, so nothing here is required. The subject is the contact a push
    # service may use if this sender misbehaves; it defaults to mailto:<admin_email>.
    vapid_subject: str = ""
    # Photos captured longer ago than this are never announced: a backfill is history,
    # not news, and a season of it arriving as pushes would get the app muted.
    notify_lookback_hours: int = 24

    # Storage / retention
    media_root: str = "/data/media"
    models_root: str = "/data/models"
    media_retention_days: int = 30
    # Where pipeline.py writes pipeline.log. Unset: the logs folder beside the data
    # folder when there is one (C:\GameSense\logs), else <data>/logs (app.jobs).
    log_dir: str = ""

    # CORS — frontend dev origins
    cors_origins: list[str] = [
        "http://localhost:8080",
        "http://localhost:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
