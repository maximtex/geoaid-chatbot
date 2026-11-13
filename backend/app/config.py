from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

_SQLITE_PREFIX = "sqlite:///"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "GeoAid Core API"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False

    # Meta WhatsApp Cloud API
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WEBHOOK_VERIFY_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""
    GRAPH_API_VERSION: str = "v21.0"
    GRAPH_API_BASE_URL: str = "https://graph.facebook.com"

    # Persistencia
    DATABASE_URL: str = "sqlite:///./geoaid.db"
    MEDIA_DIR: Path = Path("./data/media")
    MAX_MEDIA_BYTES: int = 10 * 1024 * 1024

    # Demo / integración con la web
    DEMO_PHONES: str = ""  # "573001234567,573109876543": pueden usar "reiniciar demo"
    CORS_ORIGINS: str = "https://geo-aid-coral.vercel.app,http://localhost:3000"

    @property
    def demo_phones(self) -> set[str]:
        return {"".join(ch for ch in p if ch.isdigit()) for p in self.DEMO_PHONES.split(",") if p.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @field_validator("DATABASE_URL")
    @classmethod
    def _resolve_sqlite_path(cls, value: str) -> str:
        """Las rutas SQLite relativas se resuelven contra backend/, no contra el directorio actual."""
        if value.startswith(_SQLITE_PREFIX) and value != "sqlite:///:memory:":
            path = Path(value[len(_SQLITE_PREFIX):])
            if not path.is_absolute():
                return _SQLITE_PREFIX + (BACKEND_DIR / path).resolve().as_posix()
        return value

    @field_validator("MEDIA_DIR")
    @classmethod
    def _resolve_media_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
