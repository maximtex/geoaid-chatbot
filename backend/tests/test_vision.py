"""Semáforo de daño (app/services/vision_service.py) sin llamar a la API real."""

import base64
import io
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from PIL import Image

from app.db.models import DamageLevel
from app.services import vision_service as vs


class FakeMessages:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def tool_response(**data):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="registrar_evaluacion", input=data)])


def evaluation(nivel="ROJO", confianza=0.85, muestra_edificacion=True, hallazgos=("columna fracturada",)):
    return tool_response(
        muestra_edificacion=muestra_edificacion, nivel=nivel, confianza=confianza, hallazgos=list(hallazgos)
    )


@pytest.fixture
def api(monkeypatch):
    """Configura una clave falsa y reemplaza el cliente de Anthropic. Devuelve el FakeMessages para inspeccionarlo."""
    messages = FakeMessages(result=evaluation())
    monkeypatch.setattr(vs, "get_settings", lambda: SimpleNamespace(ANTHROPIC_API_KEY="clave", VISION_MODEL="modelo"))
    monkeypatch.setattr(vs, "_client", lambda key: SimpleNamespace(messages=messages))
    return messages


@pytest.fixture
def photo(tmp_path):
    def make(name="dano.jpg", size=(800, 600)):
        path = tmp_path / name
        Image.new("RGB", size, (120, 110, 100)).save(path, format="JPEG")
        return path

    return make


def test_sin_clave_queda_sin_clasificar_y_no_llama_a_la_api(monkeypatch, photo):
    monkeypatch.setattr(vs, "get_settings", lambda: SimpleNamespace(ANTHROPIC_API_KEY="", VISION_MODEL="modelo"))
    monkeypatch.setattr(vs, "_client", lambda key: pytest.fail("No debería llamar a la API sin clave"))
    assert vs.analyze_building_damage([photo()]) == vs.DamageAssessment(level=None)


def test_clasifica_con_el_nivel_del_modelo(api, photo):
    result = vs.analyze_building_damage([photo()])
    assert result.level == DamageLevel.ROJO
    assert result.confidence == 0.85
    assert result.notes == ("columna fracturada",)
    call = api.calls[0]
    assert call["model"] == "modelo"
    assert call["tool_choice"] == {"type": "tool", "name": "registrar_evaluacion"}


@pytest.mark.parametrize("nivel", ["VERDE", "AMARILLO", "ROJO"])
def test_los_tres_colores(api, photo, nivel):
    api.result = evaluation(nivel=nivel)
    assert vs.analyze_building_damage([photo()]).level == DamageLevel(nivel)


def test_foto_que_no_es_una_edificacion_queda_sin_clasificar(api, photo):
    api.result = evaluation(nivel="VERDE", muestra_edificacion=False, hallazgos=())
    assert vs.analyze_building_damage([photo()]).level is None


def test_el_modelo_dice_sin_clasificar(api, photo):
    api.result = evaluation(nivel="SIN_CLASIFICAR", confianza=0.9)
    assert vs.analyze_building_damage([photo()]).level is None


def test_confianza_baja_queda_para_el_revisor(api, photo):
    api.result = evaluation(confianza=vs.MIN_CONFIDENCE - 0.01)
    result = vs.analyze_building_damage([photo()])
    assert result.level is None
    assert result.confidence == pytest.approx(vs.MIN_CONFIDENCE - 0.01)


@pytest.mark.parametrize("confianza", [None, "mucha", float("nan")])
def test_confianza_invalida_queda_sin_clasificar(api, photo, confianza):
    api.result = evaluation(confianza=confianza)
    assert vs.analyze_building_damage([photo()]).level is None


def test_respuesta_sin_la_herramienta_queda_sin_clasificar(api, photo):
    api.result = SimpleNamespace(content=[SimpleNamespace(type="text", text="ROJO")])
    assert vs.analyze_building_damage([photo()]) == vs.DamageAssessment(level=None)


def test_error_de_la_api_queda_sin_clasificar(api, photo):
    api.error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    assert vs.analyze_building_damage([photo()]) == vs.DamageAssessment(level=None)


def test_salta_las_fotos_que_no_se_pueden_abrir(api, photo, tmp_path):
    broken = tmp_path / "rota.jpg"
    broken.write_bytes(b"esto no es una imagen")
    vs.analyze_building_damage([broken, photo()])
    images = [block for block in api.calls[0]["messages"][0]["content"] if block["type"] == "image"]
    assert len(images) == 1


def test_si_ninguna_foto_abre_no_llama_a_la_api(api, tmp_path):
    broken = tmp_path / "rota.jpg"
    broken.write_bytes(b"esto no es una imagen")
    assert vs.analyze_building_damage([broken]) == vs.DamageAssessment(level=None)
    assert api.calls == []


def test_achica_las_fotos_grandes_y_envia_maximo_tres(api, photo):
    paths = [photo(f"dano{i}.png", size=(4000, 3000)) for i in range(4)]
    vs.analyze_building_damage(paths)
    images = [block for block in api.calls[0]["messages"][0]["content"] if block["type"] == "image"]
    assert len(images) == vs.MAX_PHOTOS
    for block in images:
        assert block["source"]["media_type"] == "image/jpeg"
        sent = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
        assert max(sent.size) <= vs.MAX_LONG_EDGE
