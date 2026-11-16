"""Modo en vivo (app/drone/live.py): cuándo pregunta y cómo mueve los recuadros, sin la API real."""

from concurrent.futures import Future

import pytest
from PIL import Image, ImageDraw

cv2 = pytest.importorskip("cv2", reason="sin OpenCV: pip install -r requirements-dron.txt")
np = pytest.importorskip("numpy")

from app.drone import live
from app.drone.boxes import Box

BOX = Box(0.5, 0.5, 0.6, 0.6, "ROJO", 0.9, "colapso")


def _city(seed: int, width=1400, height=800) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = Image.new("RGB", (width, height), (90, 90, 90))
    draw = ImageDraw.Draw(image)
    for _ in range(600):
        x, y = rng.integers(0, width), rng.integers(0, height)
        w, h = rng.integers(10, 60), rng.integers(10, 60)
        draw.rectangle((x, y, x + w, y + h), fill=tuple(int(c) for c in rng.integers(0, 255, 3)))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


CITY, OTHER = _city(1), _city(2)


def _frame(i: int, city=CITY) -> np.ndarray:
    """La cámara se corre 4 px a la derecha por cuadro: la imagen se mueve 4 px a la izquierda."""
    return city[100:460, 100 + 4 * i : 740 + 4 * i].copy()


class ManualExecutor:
    """Guarda las consultas para responderlas cuando la prueba quiera (como si Claude tardara)."""

    def __init__(self) -> None:
        self.futures: list[Future] = []

    def submit(self, fn, *args) -> Future:
        future = Future()
        self.futures.append(future)
        return future

    def shutdown(self, **kwargs) -> None:
        pass


@pytest.fixture
def setup(tmp_path):
    now = [0.0]
    executor = ManualExecutor()
    session = live.LiveSession(lambda path: None, tmp_path, every_s=4, max_queries=5, clock=lambda: now[0], executor=executor)
    return session, executor, now


def test_pregunta_cuando_se_estabiliza_y_mueve_la_respuesta_hasta_el_cuadro_actual(setup):
    session, executor, _ = setup
    for i in range(3):
        assert session.process(_frame(i)) == []
    assert session.queries == 0  # todavía no hay 3 cuadros seguidos con seguimiento
    session.process(_frame(3))
    assert session.queries == 1 and session.status.startswith("analizando")

    for i in range(4, 10):  # Claude tarda: la cámara sigue moviéndose
        session.process(_frame(i))
    executor.futures[0].set_result([BOX])
    [(corners, box)] = session.process(_frame(10))
    # Se preguntó en el cuadro 3; en el 10 la casa ya se corrió 7 × 4 px a la izquierda.
    assert box == BOX
    assert corners[0][0] == pytest.approx(0.5 * 640 - 28, abs=2)
    assert session.status is None


def test_no_vuelve_a_preguntar_hasta_que_la_vista_cambia(setup):
    session, executor, now = setup
    for i in range(4):
        session.process(_frame(i))
    executor.futures[0].set_result([BOX])
    now[0] = 100.0  # ya pasó el tiempo mínimo entre consultas
    for i in range(4, 40):  # 36 × 4 px: la vista sigue compartiendo más del 70 %
        session.process(_frame(i))
    assert session.queries == 1
    for i in range(40, 60):
        session.process(_frame(i))
    assert session.queries == 2


def test_un_corte_descarta_la_respuesta_pendiente_y_pregunta_de_una(setup):
    session, executor, _ = setup
    for i in range(4):
        session.process(_frame(i))
    for i in range(5):  # corte a otra escena antes de que Claude responda
        session.process(_frame(i, OTHER))
    executor.futures[0].set_result([BOX])
    session.process(_frame(5, OTHER))
    assert session.boxes == []  # era de la escena anterior
    assert session.status.startswith("analizando")  # ya va la consulta de la escena nueva
    assert session.queries == 2  # en la escena nueva pregunta sin esperar los 4 s


def test_avisa_cuando_la_respuesta_llega_tarde(tmp_path):
    now = [0.0]
    executor = ManualExecutor()
    session = live.LiveSession(lambda path: None, tmp_path, max_queries=1, clock=lambda: now[0], executor=executor)
    for i in range(4):
        session.process(_frame(i))
    session.process(_frame(0, OTHER))  # corte
    executor.futures[0].set_result([BOX])
    session.process(_frame(1, OTHER))
    assert session.status == "la toma cambió antes de la respuesta"
    now[0] = 10.0
    assert session.status == "tope de 1 consultas"


def test_respeta_el_tope_de_consultas(tmp_path):
    executor = ManualExecutor()
    session = live.LiveSession(lambda path: None, tmp_path, max_queries=1, clock=lambda: 0.0, executor=executor)
    for i in range(4):
        session.process(_frame(i))
    executor.futures[0].set_result([BOX])
    for i in range(5):
        session.process(_frame(i, OTHER))
    assert session.queries == 1 and session.status == "tope de 1 consultas"


def test_si_la_ia_no_responde_lo_avisa(setup):
    session, executor, _ = setup
    for i in range(4):
        session.process(_frame(i))
    executor.futures[0].set_result(None)
    assert session.process(_frame(4)) == []
    assert session.status == "la IA no respondió"


def test_la_tecla_c_pregunta_ya(setup):
    session, executor, _ = setup
    for i in range(4):
        session.process(_frame(i))
    executor.futures[0].set_result([BOX])
    session.process(_frame(4))
    session.ask_now()
    session.process(_frame(5))
    assert session.queries == 2


def test_superposicion_de_vistas():
    assert live._overlap(np.eye(3), 640, 360) == pytest.approx(1.0)
    shifted = np.array([[1, 0, -320], [0, 1, 0], [0, 0, 1]], dtype=float)
    assert live._overlap(shifted, 640, 360) == pytest.approx(0.5)
