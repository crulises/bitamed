"""Application configuration.

Every value comes from the environment. Nothing here has a production-safe
default: SECRET_KEY and IP_HASH_SALT must be set explicitly or the app
refuses to start outside development.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    base_url: str = "http://localhost:8000"
    secret_key: str

    database_url: str
    redis_url: str

    # --- sessions ---------------------------------------------------------
    session_cookie_name: str = "bitamed_session"
    # Absolute lifetime. A session older than this dies even if in use.
    session_max_age_seconds: int = 60 * 60 * 24 * 14
    # Idle timeout. Shorter, because a phone left on a table is the realistic
    # threat model here, not a stolen cookie.
    session_idle_seconds: int = 60 * 60 * 12

    # --- login throttling -------------------------------------------------
    login_max_attempts: int = 8
    login_lockout_minutes: int = 15

    # --- invitations ------------------------------------------------------
    invitation_ttl_hours: int = 168  # 7 days
    password_reset_ttl_minutes: int = 30

    # --- registration -----------------------------------------------------
    allow_open_registration: bool = False
    instance_admin_email: str = ""

    # --- privacy ----------------------------------------------------------
    # Raw IPs are never stored. This salt makes the hashes non-reversible
    # across deployments; rotating it breaks correlation of old log entries,
    # which is a feature, not a bug.
    ip_hash_salt: str

    # --- i18n -------------------------------------------------------------
    default_locale: str = "es"
    supported_locales: str = "es,pt,en"
    default_timezone: str = "America/Argentina/Buenos_Aires"

    min_password_length: int = Field(default=12, ge=8)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def locales(self) -> list[str]:
        return [x.strip() for x in self.supported_locales.split(",") if x.strip()]

    @field_validator("secret_key", "ip_hash_salt")
    @classmethod
    def _reject_placeholders(cls, v: str) -> str:
        if v.startswith("change-me") or len(v) < 32:
            # Fails loudly at boot rather than silently shipping a known key.
            raise ValueError(
                "secret_key and ip_hash_salt must be set to at least 32 random "
                "characters. Generate with: openssl rand -hex 32"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
