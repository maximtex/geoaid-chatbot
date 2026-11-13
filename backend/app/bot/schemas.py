"""Validación del JSON que envía Meta y su conversión a un mensaje normalizado.

Referencia: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
"""

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


class _MetaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Profile(_MetaModel):
    name: str | None = None


class Contact(_MetaModel):
    wa_id: str
    profile: Profile | None = None


class Metadata(_MetaModel):
    phone_number_id: str | None = None
    display_phone_number: str | None = None


class TextBody(_MetaModel):
    body: str = ""


class Reply(_MetaModel):
    id: str
    title: str | None = None


class Interactive(_MetaModel):
    type: str
    button_reply: Reply | None = None
    list_reply: Reply | None = None


class TemplateButton(_MetaModel):
    payload: str | None = None
    text: str | None = None


class Location(_MetaModel):
    latitude: float
    longitude: float
    name: str | None = None
    address: str | None = None


class Media(_MetaModel):
    id: str
    mime_type: str | None = None
    sha256: str | None = None
    caption: str | None = None
    filename: str | None = None


class Message(_MetaModel):
    from_: str = Field(alias="from")
    id: str
    timestamp: str | None = None
    type: str
    text: TextBody | None = None
    interactive: Interactive | None = None
    button: TemplateButton | None = None
    location: Location | None = None
    image: Media | None = None
    document: Media | None = None


class ChangeValue(_MetaModel):
    messaging_product: str | None = None
    metadata: Metadata | None = None
    contacts: list[Contact] = []
    messages: list[dict] = []  # se validan uno por uno para que un mensaje raro no tumbe a los demás
    statuses: list[dict] = []


class Change(_MetaModel):
    field: str | None = None
    value: ChangeValue


class Entry(_MetaModel):
    id: str | None = None
    changes: list[Change] = []


class WebhookPayload(_MetaModel):
    object: str | None = None
    entry: list[Entry] = []


class MessageKind(StrEnum):
    TEXT = "TEXT"
    REPLY = "REPLY"  # botón o lista interactiva
    LOCATION = "LOCATION"
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    OTHER = "OTHER"  # audio, sticker, ubicación en tiempo real, etc.


class IncomingMessage(BaseModel):
    wamid: str
    from_phone: str
    profile_name: str | None = None
    kind: MessageKind
    text: str | None = None
    reply_id: str | None = None
    reply_title: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    media_id: str | None = None
    mime_type: str | None = None

    @property
    def is_image(self) -> bool:
        """Foto normal, o archivo adjunto que en realidad es una imagen."""
        if self.kind == MessageKind.IMAGE:
            return True
        return self.kind == MessageKind.DOCUMENT and (self.mime_type or "").startswith("image/")


def _normalize(message: Message, profile_name: str | None) -> IncomingMessage:
    data: dict = {"wamid": message.id, "from_phone": message.from_, "profile_name": profile_name}

    if message.type == "text" and message.text is not None:
        data.update(kind=MessageKind.TEXT, text=message.text.body)
    elif message.type == "interactive" and message.interactive is not None:
        reply = message.interactive.button_reply or message.interactive.list_reply
        if reply is None:
            data.update(kind=MessageKind.OTHER)
        else:
            data.update(kind=MessageKind.REPLY, reply_id=reply.id, reply_title=reply.title)
    elif message.type == "button" and message.button is not None:
        data.update(kind=MessageKind.REPLY, reply_id=message.button.payload, reply_title=message.button.text)
    elif message.type == "location" and message.location is not None:
        data.update(
            kind=MessageKind.LOCATION,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
        )
    elif message.type == "image" and message.image is not None:
        data.update(kind=MessageKind.IMAGE, media_id=message.image.id, mime_type=message.image.mime_type)
    elif message.type == "document" and message.document is not None:
        data.update(kind=MessageKind.DOCUMENT, media_id=message.document.id, mime_type=message.document.mime_type)
    else:
        data.update(kind=MessageKind.OTHER)

    return IncomingMessage(**data)


def extract_messages(payload: dict, expected_phone_number_id: str | None = None) -> list[IncomingMessage]:
    """Devuelve los mensajes de usuarios contenidos en un webhook. Ignora notificaciones de estado."""
    try:
        parsed = WebhookPayload.model_validate(payload)
    except ValidationError:
        logger.warning("Webhook con estructura inesperada; se ignora")
        return []

    result: list[IncomingMessage] = []
    for entry in parsed.entry:
        for change in entry.changes:
            value = change.value
            phone_id = value.metadata.phone_number_id if value.metadata else None
            if expected_phone_number_id and phone_id and phone_id != expected_phone_number_id:
                logger.warning("Webhook para otro número (%s); se ignora", phone_id)
                continue

            names = {c.wa_id: (c.profile.name if c.profile else None) for c in value.contacts}
            for raw in value.messages:
                try:
                    message = Message.model_validate(raw)
                except ValidationError:
                    logger.warning("Mensaje con estructura inesperada; se ignora")
                    continue
                result.append(_normalize(message, names.get(message.from_)))
    return result
