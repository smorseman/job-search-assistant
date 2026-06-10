from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # USAJOBS
    USAJOBS_API_KEY: str = ""
    USAJOBS_EMAIL: str = ""

    # Adzuna
    ADZUNA_APP_ID: str = ""
    ADZUNA_API_KEY: str = ""

    # Google
    GOOGLE_CREDENTIALS_PATH: str = "credentials.json"
    GOOGLE_TOKEN_PATH: str = "token.json"
    TRACKER_SHEET_ID: str = ""
    DRIVE_ROOT_FOLDER_ID: str = ""
    GMAIL_ALERT_LABEL: str = "job-alerts"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Local DB
    DB_PATH: str = "data/jobs.db"

    # Runtime
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    DRY_RUN: bool = False

    # Profile — real file is gitignored; copy from .example template
    PROFILE_PATH: str = "profile/james_profile.yaml"
    PROFILE_TEMPLATE_PATH: str = "profile/james_profile.example.yaml"

    @field_validator("DB_PATH", mode="before")
    @classmethod
    def ensure_data_dir(cls, v: str) -> str:
        Path(v).parent.mkdir(parents=True, exist_ok=True)
        return v


settings = Settings()
