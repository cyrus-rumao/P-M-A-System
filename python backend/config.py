from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    node_env: str = "development"
    port: int = 5000
    base_path: str = "/api"
    mongo_uri: str = ""
    redis_url: str | None = None
    session_secret: str = ""
    session_expires_in: str = "1d"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_callback_url: str = ""
    frontend_origin: str = "http://localhost:5173"
    frontend_google_callback_url: str = "http://localhost:5173/google/callback"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
