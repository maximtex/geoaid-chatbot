from app.bot.schemas import MessageKind, extract_messages


def wrap(*messages: dict, phone_id: str = "PHONE_ID", contacts=None) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_id},
                            "contacts": contacts or [{"profile": {"name": "Ana"}, "wa_id": "57300"}],
                            "messages": list(messages),
                        },
                    }
                ]
            }
        ],
    }


def base(type_: str, **extra) -> dict:
    return {"from": "57300", "id": f"wamid.{type_}", "timestamp": "1", "type": type_, **extra}


def test_texto():
    [msg] = extract_messages(wrap(base("text", text={"body": "Hola"})))
    assert (msg.kind, msg.text, msg.profile_name, msg.from_phone) == (MessageKind.TEXT, "Hola", "Ana", "57300")


def test_boton_y_lista():
    button = base("interactive", interactive={"type": "button_reply", "button_reply": {"id": "terms:accept", "title": "Acepto"}})
    row = base("interactive", interactive={"type": "list_reply", "list_reply": {"id": "tenure:OTRO", "title": "Otro"}})
    row["id"] = "wamid.list"
    first, second = extract_messages(wrap(button, row))
    assert (first.kind, first.reply_id) == (MessageKind.REPLY, "terms:accept")
    assert (second.kind, second.reply_id) == (MessageKind.REPLY, "tenure:OTRO")


def test_ubicacion():
    [msg] = extract_messages(wrap(base("location", location={"latitude": 4.5, "longitude": -75.6})))
    assert (msg.kind, msg.latitude, msg.longitude) == (MessageKind.LOCATION, 4.5, -75.6)


def test_imagen_y_documento():
    image = base("image", image={"id": "MEDIA1", "mime_type": "image/jpeg", "sha256": "x"})
    doc = base("document", document={"id": "MEDIA2", "mime_type": "image/png", "filename": "cedula.png"})
    pdf = base("document", document={"id": "MEDIA3", "mime_type": "application/pdf"})
    doc["id"], pdf["id"] = "wamid.doc", "wamid.pdf"
    a, b, c = extract_messages(wrap(image, doc, pdf))
    assert a.kind == MessageKind.IMAGE and a.media_id == "MEDIA1" and a.is_image
    assert b.kind == MessageKind.DOCUMENT and b.is_image
    assert c.kind == MessageKind.DOCUMENT and not c.is_image


def test_tipos_no_soportados_quedan_como_other():
    [msg] = extract_messages(wrap(base("unsupported", errors=[{"code": 131051}])))
    assert msg.kind == MessageKind.OTHER


def test_statuses_y_payload_raro_no_generan_mensajes():
    assert extract_messages({"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}) == []
    assert extract_messages({"entry": "no es lista"}) == []
    assert extract_messages({}) == []


def test_mensaje_malformado_no_tumba_a_los_demas():
    broken = {"id": "sin-from", "type": "text"}
    [msg] = extract_messages(wrap(broken, base("text", text={"body": "ok"})))
    assert msg.text == "ok"


def test_filtra_por_numero_de_telefono():
    payload = wrap(base("text", text={"body": "hola"}), phone_id="OTRO")
    assert extract_messages(payload, expected_phone_number_id="PHONE_ID") == []
    assert len(extract_messages(payload, expected_phone_number_id=None)) == 1
