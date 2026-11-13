import itertools
from pathlib import Path

import pytest

from app.bot.messages import Buttons, ListMessage, LocationRequest, Outgoing, Text
from app.bot.meta_client import DownloadedMedia, MetaAPIError
from app.bot.schemas import IncomingMessage, MessageKind
from app.bot.state_manager import Bot
from app.config import Settings
from app.db import models  # noqa: F401
from app.db.database import Base, make_engine, make_session_factory
from app.services.ocr_service import IdData
from app.services.vision_service import DamageAssessment


class FakeMetaClient:
    """Reemplaza a Meta: guarda lo que el bot envía y sirve imágenes falsas."""

    def __init__(self):
        self.sent: list[tuple[str, Outgoing]] = []
        self.read: list[str] = []
        self.fail_download = False

    async def send(self, to: str, message: Outgoing) -> dict:
        self.sent.append((to, message))
        return {}

    async def mark_as_read(self, message_id: str) -> None:
        self.read.append(message_id)

    async def download_media(self, media_id: str) -> DownloadedMedia:
        if self.fail_download:
            raise MetaAPIError("descarga simulada fallida")
        # El contenido depende del media_id: el mismo id produce la misma "foto" (mismo sha256).
        return DownloadedMedia(content=f"imagen-{media_id}".encode(), mime_type="image/jpeg")


class FakeOcr:
    def __init__(self):
        self.result = IdData(full_name="Ana María Pérez", document_id="1.015.234.890", confidence=0.9)
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> IdData:
        self.calls.append(path)
        return self.result


class Chat:
    """Simula a un ciudadano escribiéndole al bot."""

    _ids = itertools.count(1)

    def __init__(self, bot: Bot, client: FakeMetaClient, phone: str = "573001234567", name: str = "Ana"):
        self.bot, self.client, self.phone, self.name = bot, client, phone, name
        self._seen = 0

    async def _send(self, **fields) -> list[Outgoing]:
        msg = IncomingMessage(wamid=f"wamid.{next(self._ids)}", from_phone=self.phone, profile_name=self.name, **fields)
        await self.bot.handle(msg)
        return self.replies()

    def replies(self) -> list[Outgoing]:
        mine = [m for to, m in self.client.sent if to == self.phone]
        new, self._seen = mine[self._seen:], len(mine)
        return new

    async def text(self, body: str):
        return await self._send(kind=MessageKind.TEXT, text=body)

    async def reply(self, reply_id: str):
        return await self._send(kind=MessageKind.REPLY, reply_id=reply_id)

    async def location(self, lat: float = 4.711, lon: float = -74.072):
        return await self._send(kind=MessageKind.LOCATION, latitude=lat, longitude=lon)

    async def image(self, media_id: str):
        return await self._send(kind=MessageKind.IMAGE, media_id=media_id, mime_type="image/jpeg")

    async def document(self, media_id: str, mime: str):
        return await self._send(kind=MessageKind.DOCUMENT, media_id=media_id, mime_type=mime)


def bodies(messages: list[Outgoing]) -> str:
    """Todo el texto de una lista de respuestas, para hacer asserts con `in`."""
    parts = []
    for m in messages:
        if isinstance(m, (Text, Buttons, ListMessage, LocationRequest)):
            parts.append(m.body)
    return "\n".join(parts)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DEBUG=False,
        WHATSAPP_TOKEN="token-de-prueba",
        WHATSAPP_PHONE_NUMBER_ID="PHONE_ID",
        WEBHOOK_VERIFY_TOKEN="verify-me",
        WHATSAPP_APP_SECRET="app-secret",
        GRAPH_API_VERSION="v21.0",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        MEDIA_DIR=tmp_path / "media",
    )


@pytest.fixture
def session_factory(settings: Settings):
    engine = make_engine(settings.DATABASE_URL)
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def client() -> FakeMetaClient:
    return FakeMetaClient()


@pytest.fixture
def ocr() -> FakeOcr:
    return FakeOcr()


@pytest.fixture
def bot(settings, client, session_factory, ocr) -> Bot:
    return Bot(
        settings=settings,
        client=client,
        session_factory=session_factory,
        ocr=ocr,
        vision=lambda paths: DamageAssessment(level=models.DamageLevel.AMARILLO, confidence=0.7),
    )


@pytest.fixture
def chat(bot, client) -> Chat:
    return Chat(bot, client)
