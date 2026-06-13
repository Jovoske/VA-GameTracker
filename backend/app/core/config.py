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
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

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
    sync_interval_minutes: int = 15

    # Storage / retention
    media_root: str = "/data/media"
    models_root: str = "/data/models"
    media_retention_days: int = 30

    # CORS — frontend dev origins
    cors_origins: list[str] = [
        "http://localhost:8080",
        "http://localhost:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
