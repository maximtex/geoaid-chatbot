"""Mensajes salientes y su conversión al JSON de la WhatsApp Cloud API."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Text:
    body: str
    preview_url: bool = False  # True: WhatsApp muestra la tarjeta del primer enlace


@dataclass(frozen=True)
class Buttons:
    """Hasta 3 botones de respuesta rápida. Cada botón: (id, título <= 20 caracteres)."""

    body: str
    buttons: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ListMessage:
    """Lista desplegable de hasta 10 opciones. Cada fila: (id, título <= 24, descripción <= 72)."""

    body: str
    button: str
    section_title: str
    rows: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class LocationRequest:
    """Mensaje con el botón nativo 'Enviar ubicación'."""

    body: str


Outgoing = Text | Buttons | ListMessage | LocationRequest


def build_payload(to: str, message: Outgoing) -> dict:
    base = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to}

    match message:
        case Text(body=body, preview_url=preview_url):
            return {**base, "type": "text", "text": {"preview_url": preview_url, "body": body}}
        case Buttons(body=body, buttons=buttons):
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body},
                    "action": {
                        "buttons": [{"type": "reply", "reply": {"id": i, "title": t}} for i, t in buttons]
                    },
                },
            }
        case ListMessage(body=body, button=button, section_title=section_title, rows=rows):
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body},
                    "action": {
                        "button": button,
                        "sections": [
                            {
                                "title": section_title,
                                # La descripción es opcional en Meta: si va vacía, se omite.
                                "rows": [
                                    {"id": i, "title": t, **({"description": d} if d else {})} for i, t, d in rows
                                ],
                            }
                        ],
                    },
                },
            }
        case LocationRequest(body=body):
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "location_request_message",
                    "body": {"text": body},
                    "action": {"name": "send_location"},
                },
            }
    raise TypeError(f"Mensaje no soportado: {message!r}")
