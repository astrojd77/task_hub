"""Application configuration.

Everything database-specific is behind ``database_url``. Moving from the dev
SQLite/Postgres database to prod Oracle is an env change, not a code change:

    dev  sqlite+pysqlite:///./task_hub.db
    dev  postgresql+psycopg://taskhub:taskhub@localhost:5432/taskhub
    prod oracle+oracledb://user:pass@host:1521/?service_name=XEPDB1

``oracledb`` runs in thin mode by default, so no Oracle Instant Client install
is required on the app host.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: object) -> object:
    """Allow ``A,B,C`` in env vars for list fields, not just JSON."""
    if isinstance(value, str) and not value.strip().startswith("["):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Task Hub"
    environment: str = "dev"
    debug: bool = True

    database_url: str = "sqlite+pysqlite:///./task_hub.db"
    db_echo: bool = False

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    #: Directory holding the built frontend. When it exists the API also serves
    #: the SPA, which is how the container image ships: one process, one port,
    #: one Route, and no CORS in production. Absent in local dev, where Vite
    #: serves the frontend and proxies /api.
    static_dir: str = "static"

    # Which adapters are live. Enabling a provider is config, never code.
    enabled_sources: list[str] = ["csv", "jira", "email"]
    enabled_destinations: list[str] = ["local", "jira"]

    _split = field_validator(
        "cors_origins", "enabled_sources", "enabled_destinations", mode="before"
    )(_split_csv)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
