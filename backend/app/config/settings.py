"""Centralized application configuration (Milestone M0.2B).

A single, strongly-typed `Settings` object every future module imports
instead of reading `os.environ` directly — per the Technical Design
Document's Configuration Management strategy (Section 14): configuration
is loaded once, validated at startup, and fails loudly if misconfigured
rather than surfacing as a mysterious runtime bug later.

This module does NOT open any connection to Postgres, Redis, Qdrant,
MinIO, or a mail server — it only describes and validates the settings
those future modules will need. See app/config/__init__.py for the
shared `settings` instance every module should import.
"""

from typing import Annotated, Literal

from pydantic import Field, PositiveInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A TCP port is always in [1, 65535] — used for every *_PORT field below so
# the range check is defined once, not repeated as five near-identical
# validators.
Port = Annotated[int, Field(ge=1, le=65535)]


class _BaseEnvSettings(BaseSettings):
    """Shared base for every settings group below.

    Reads from a `.env` file in the current working directory, ignores
    variables it doesn't recognize (so this repository's other `.env`
    consumers — e.g. Docker Compose — can share a file without causing
    validation errors here), and treats variable names as case-sensitive
    to match normal shell/environment convention.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# ---------------------------------------------------------------------------
# Database — PostgreSQL connection parameters only. No engine, session, or
# connection is created here; that begins with app/db/ in a later milestone.
# ---------------------------------------------------------------------------
class DatabaseSettings(_BaseEnvSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    HOST: str = "localhost"
    PORT: Port = 5432
    DB: str = "nexus_ai"
    USER: str  # required — no safe default for a real credential
    PASSWORD: str  # required — no safe default for a real credential


# ---------------------------------------------------------------------------
# Redis — cache / session store / Celery broker connection parameters only.
# No client is constructed here.
# ---------------------------------------------------------------------------
class RedisSettings(_BaseEnvSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    HOST: str = "localhost"
    PORT: Port = 6379


# ---------------------------------------------------------------------------
# Qdrant — vector store connection parameters only.
# ---------------------------------------------------------------------------
class QdrantSettings(_BaseEnvSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_")

    HOST: str = "localhost"
    PORT: Port = 6333


# ---------------------------------------------------------------------------
# MinIO — S3-compatible object storage connection parameters only.
# ---------------------------------------------------------------------------
class MinIOSettings(_BaseEnvSettings):
    model_config = SettingsConfigDict(env_prefix="MINIO_")

    ENDPOINT: str = "localhost:9000"
    ROOT_USER: str  # required — no safe default for a real credential
    ROOT_PASSWORD: str  # required — no safe default for a real credential
    BUCKET: str = "nexus-documents"

    @field_validator("ENDPOINT")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        """Must be a bare `host:port` — no scheme, no trailing slash."""
        host, sep, port_str = v.rpartition(":")
        if not sep or not host:
            raise ValueError(
                "MINIO_ENDPOINT must be in the form 'host:port' (e.g. 'localhost:9000')"
            )
        if not port_str.isdigit() or not (1 <= int(port_str) <= 65535):
            raise ValueError("MINIO_ENDPOINT must end with a valid port number (1-65535)")
        return v


# ---------------------------------------------------------------------------
# Mail — outbound SMTP connection parameters only (Mailpit locally).
# Username/password are optional: local Mailpit requires no auth, unlike a
# real provider in staging/production.
# ---------------------------------------------------------------------------
class MailSettings(_BaseEnvSettings):
    model_config = SettingsConfigDict(env_prefix="MAIL_")

    HOST: str = "localhost"
    PORT: Port = 1025
    USERNAME: str | None = None
    PASSWORD: str | None = None
    FROM: str = "noreply@nexus-ai.local"


# ---------------------------------------------------------------------------
# The top-level Settings object. Composes the grouped settings above with
# the application-, security-, and AI-related variables that don't share a
# common prefix (per the exact variable names required by this milestone).
# ---------------------------------------------------------------------------
class Settings(_BaseEnvSettings):
    # --- Application ---
    APP_NAME: str = "Nexus AI"
    APP_ENV: Literal["local", "development", "staging", "production"] = "local"
    APP_DEBUG: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: Port = 8000

    # --- Security / tokens ---
    # TTLs mirror the values already frozen in the Technical Design
    # Document, Section 5 (Authentication Flow): short-lived access token,
    # longer-lived rotating refresh token.
    SECRET_KEY: str  # required — no safe default for a real secret
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: PositiveInt = 15
    REFRESH_TOKEN_EXPIRE_DAYS: PositiveInt = 30

    # --- S1E: email verification / password reset token TTLs ---
    # UNRESOLVED CONTRACT GAP: no frozen Technical Design Document value
    # exists for either of these (the document itself is marked "not yet
    # added" in docs/architecture/README.md) — these are implementation
    # defaults, not frozen values, named clearly and centralized here
    # rather than left as a magic number in service code, per S1E's own
    # instruction for exactly this situation. 24h for verification
    # (a generous "check your email" window); 60m for password reset
    # (shorter, since a reset link is a more sensitive bearer credential
    # than a verification link).
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: PositiveInt = 24
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: PositiveInt = 60

    # --- S1G: invitation token TTL ---
    # UNRESOLVED CONTRACT GAP: same situation as the two settings above —
    # no frozen Technical Design Document value exists for how long a
    # workspace invitation link should remain valid. 7 days is a
    # reasonable default for an offer one person sends another (longer
    # than a same-session email-verification/reset link, since accepting
    # an invitation often waits on the invitee noticing the email at
    # all), named here rather than hardcoded in the invitations service.
    INVITATION_TOKEN_EXPIRE_DAYS: PositiveInt = 7

    # Skip email verification at registration — a local-dev convenience only.
    AUTO_VERIFY_EMAILS: bool = False

    # --- AI (Google Gemini) ---
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    # Comma-separated, tried in order when the primary model is overloaded,
    # rate-limited or times out. Free-tier quotas are per model (some only
    # 20 requests/day), so more than one fallback keeps answers flowing.
    GEMINI_FALLBACK_MODELS: str = "gemini-3.1-flash-lite,gemini-3.5-flash"
    GEMINI_TIMEOUT_SECONDS: PositiveInt = 45
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    # Local-disk store for uploaded originals (MinIO is not running in local dev).
    DOCUMENT_STORAGE_DIR: str = "storage"

    # --- Grouped settings ---
    # Each is independently constructed from the same environment/.env —
    # see DatabaseSettings etc. above for why this composition works
    # without an `env_nested_delimiter`.
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    minio: MinIOSettings = Field(default_factory=MinIOSettings)
    mail: MailSettings = Field(default_factory=MailSettings)
