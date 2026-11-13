"""Cliente HTTP asíncrono para la WhatsApp Cloud API (Meta Graph API)."""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.bot.messages import Outgoing, build_payload
from app.config import Settings

logger = logging.getLogger(__name__)


class MetaAPIError(Exception):
    pass


@dataclass(frozen=True)
class DownloadedMedia:
    content: bytes
    mime_type: str | None


class MetaClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        retries: int = 3,
        backoff_seconds: float = 0.5,
    ):
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._owns_http = http is None
        self._base = f"{settings.GRAPH_API_BASE_URL}/{settings.GRAPH_API_VERSION}"
        self._token = settings.WHATSAPP_TOKEN
        self._phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self._max_media_bytes = settings.MAX_MEDIA_BYTES
        self._retries = retries
        self._backoff = backoff_seconds

    @property
    def _messages_url(self) -> str:
        return f"{self._base}/{self._phone_number_id}/messages"

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(1, self._retries + 1):
            try:
                response = await self._http.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                if attempt == self._retries:
                    raise MetaAPIError(f"Error de red con Meta: {exc}") from exc
                logger.warning("Error de red con Meta (intento %s): %s", attempt, exc)
            else:
                retryable = response.status_code == 429 or response.status_code >= 500
                if not response.is_error:
                    return response
                if not retryable or attempt == self._retries:
                    raise MetaAPIError(f"Meta respondió {response.status_code}: {response.text[:500]}")
                logger.warning("Meta respondió %s (intento %s)", response.status_code, attempt)
            await asyncio.sleep(self._backoff * 2 ** (attempt - 1))
        raise MetaAPIError("Reintentos agotados")  # inalcanzable, por claridad

    async def send(self, to: str, message: Outgoing) -> dict:
        response = await self._request("POST", self._messages_url, json=build_payload(to, message))
        return response.json()

    async def mark_as_read(self, message_id: str) -> None:
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        await self._request("POST", self._messages_url, json=payload)

    async def download_media(self, media_id: str) -> DownloadedMedia:
        """Descarga en dos pasos: metadatos (URL temporal) y luego el binario, ambos con el token."""
        meta = (await self._request("GET", f"{self._base}/{media_id}")).json()
        url = meta.get("url")
        if not url:
            raise MetaAPIError("Meta no devolvió URL de descarga")
        if int(meta.get("file_size") or 0) > self._max_media_bytes:
            raise MetaAPIError("Archivo demasiado grande")

        response = await self._request("GET", url)
        if len(response.content) > self._max_media_bytes:
            raise MetaAPIError("Archivo demasiado grande")
        return DownloadedMedia(content=response.content, mime_type=meta.get("mime_type"))

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
