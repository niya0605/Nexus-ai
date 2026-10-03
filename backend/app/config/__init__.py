"""Configuration package — exposes the single, shared `settings` object.

Every other module accesses configuration exclusively via:

    from app.config import settings

No module should construct `Settings()` itself, and no module should
read `os.environ` directly — this is the one place configuration is
loaded and validated, per the Technical Design Document's Configuration
Management strategy (Section 14).
"""

from app.config.settings import Settings

settings = Settings()

__all__ = ["settings"]
