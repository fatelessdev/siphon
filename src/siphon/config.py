from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_prefix="",
        case_sensitive=False,
    )

    twitter_auth_token: str = ""
    twitter_ct0: str = ""
    twitter_cookie_string: str = ""
    database_url: str = "postgresql://localhost:5432/siphon"
    siphon_cache_dir: str = Field(
        default_factory=lambda: os.path.join(os.path.expanduser("~"), ".siphon")
    )
    siphon_log_level: str = "INFO"
    scrape_default_count: int = 50
    siphon_debug_http: bool = False


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
