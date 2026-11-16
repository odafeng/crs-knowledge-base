from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values come from GUTHUB_* environment variables; secrets are never committed."""

    model_config = SettingsConfigDict(env_prefix="GUTHUB_", frozen=True)

    environment: Literal["development", "test", "staging", "production"] = "development"
