from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values come from GUTHUB_* environment variables; secrets are never committed."""

    model_config = SettingsConfigDict(env_prefix="GUTHUB_", frozen=True)

    environment: Literal["development", "test", "staging", "production"] = "development"
    # Connects as a login role granted guthub_api (supabase/README.md). Optional only for local runs without data.
    database_url: SecretStr | None = None
    # Supabase project URL (e.g. http://127.0.0.1:54321). Access tokens are verified against its Auth JWKS; without
    # it, endpoints that need a signed-in user answer 503.
    supabase_url: str | None = None
    # Browser origins allowed to call the API (JSON list). Tokens travel in the Authorization header, never cookies.
    cors_origins: list[str] = []
    # Comment posting limits per account (ADR-0017); counted in the database, so they hold across instances.
    comment_burst_limit: int = Field(default=5, ge=1)
    comment_burst_minutes: int = Field(default=10, ge=1)
    comment_daily_limit: int = Field(default=50, ge=1)
    # Like and unlike changes a reader may make per burst window (H1 #123); repeats that change nothing are free.
    comment_like_limit: int = Field(default=60, ge=1)
    # Maintenance switch for cutover and rollback (F3 #78, docs/runbook-cutover.md): every write answers 503 with
    # Retry-After while reads keep working.
    writes_paused: bool = False
    # Web Push sender (C5 #95): the VAPID private key (base64url, Secret Manager) and a contact the push services can
    # reach (mailto: or https:). Only the announce-news job needs them; the public key lives in the web build.
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None
    # LINE daily broadcast (G3 #114): the GutHub official account's Messaging API channel access token (Secret Manager),
    # and the site origin the message links to.
    line_channel_access_token: SecretStr | None = None
    site_origin: str = "https://guthub.tw"
    # The content-requests Cloud Run job an admin's review or unpublish button starts (E6 #159), as
    # projects/<project>/locations/<region>/jobs/content-requests. Unset: requests wait for the job's next run.
    content_requests_job: str | None = None
    # The society's public doctor map, read to approve colorectal surgeons automatically (H10 #168). Unset: every
    # application waits for the maintainer.
    surgeon_roster_url: str | None = "https://www.crs.org.tw/zh-tw/map"
    # Approve at once when the map and a hospital mailbox match. Off until Supabase email confirmations are on: with
    # them off, an email change applies without confirming the new address, so the token's email proves nothing.
    surgeon_auto_approve: bool = False

    @model_validator(mode="after")
    def deployed_environments_need_a_database(self) -> Self:
        if self.environment in ("staging", "production") and self.database_url is None:
            raise ValueError(f"GUTHUB_DATABASE_URL is required in {self.environment}")
        return self
