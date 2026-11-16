"""Modo en vivo: recuadros sobre cada edificación mientras la cámara (o el dron) se mueve.

Desde la carpeta backend/:
    .venv\\Scripts\\python -m app.drone.live --fuente 0
        la cámara del PC; 1, 2… para una capturadora HDMI o el celular usado como cámara
    .venv\\Scripts\\python -m app.drone.live --fuente data\\video_turquia\\turquia_dron.mp4
        un video grabado, a velocidad real, como si fuera el vuelo (se marca "video grabado")
    .venv\\Scripts\\python -m app.drone.live --fuente rtmp://127.0.0.1/dron
        la transmisión en vivo del DJI Fly (ver el README: "Dron en vivo")

Cada cuadro se compara con el anterior para saber cómo se movió la cámara (app/drone/tracking.py).
Cuando la vista cambió y pasaron al menos `--cada` segundos, el cuadro actual se le manda a Claude en
segundo plano. La respuesta tarda unos segundos; mientras tanto se acumula el movimiento, así que los
recuadros aparecen ya corridos a donde está cada casa en ese momento y desde ahí la siguen.

Teclas: Q o Esc salir · Espacio pausa (solo video) · C preguntar ya · B borrar los recuadros.
"""

import argparse
import logging
import math
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.config import BACKEND_DIR, get_settings
from app.drone.boxes import (
    COST_PER_FRAME_USD,
    EFFORTS,
    Box,
    detect_buildings,
    draw_overlay,
)
from app.drone.flight import find_ffmpeg
from app.drone.tracking import MotionTracker, shapes_for

MAX_WIDTH = 1600  # se trabaja y se muestra a este ancho como máximo
MIN_OVERLAP = 0.7  # si la vista actual comparte menos que esto con la última consultada, toca preguntar otra vez
STABLE_FRAMES = 3  # cuadros seguidos con seguimiento antes de preguntar (evita mandar una transición)
WINDOW = "GeoAid - dron en vivo"
NOTE_S = 3.0  # cuánto se ve en pantalla un aviso como "la escena cambió"

logger = logging.getLogger(__name__)

Detector = Callable[[Path], list[Box] | None]


@dataclass
class _Pending:
    future: Future
    number: int
    sent_at: float
    to_now: np.ndarray = field(default_factory=lambda: np.eye(3))  # del cuadro enviado al cuadro actual
    valid: bool = True  # deja de servir si la cámara corta o se pierde el seguimiento


class LiveSession:
    """Lleva los recuadros vivos: decide cuándo preguntarle a Claude y los mueve con la cámara."""

    def __init__(
        self,
        detector: Detector,
        work_dir: Path,
        every_s: float = 4.0,
        max_queries: int = 40,
        clock: Callable[[], float] = time.monotonic,
        executor=None,
    ) -> None:
        self.detector, self.work_dir = detector, work_dir
        self.every_s, self.max_queries, self.clock = every_s, max_queries, clock
        self.executor = executor or ThreadPoolExecutor(max_workers=1)
        self.tracker = MotionTracker()
        self.boxes: list[Box] = []
        self.view_to_now: np.ndarray | None = None  # del último cuadro respondido al cuadro actual
        self.pending: _Pending | None = None
        self.queries = 0
        self.failed = False
        self._last_query = -math.inf
        self._stable = 0
        self._force = False
        self._note: tuple[str, float] | None = None  # aviso temporal y hasta cuándo se muestra

    # --- cada cuadro ---

    def process(self, frame: np.ndarray) -> list:
        height, width = frame.shape[:2]
        self._collect()  # lo que llegó hasta el cuadro anterior; abajo se mueve hasta este
        step = self.tracker.step(frame)
        if step is None:  # primer cuadro, corte o seguimiento perdido: lo anterior ya no corresponde
            self.boxes, self.view_to_now, self._stable = [], None, 0
            self._last_query = -math.inf  # vista nueva: se pregunta apenas se estabilice, sin esperar `every_s`
            if self.pending and self.pending.valid:
                self.pending.valid = False
                logger.info("La toma cambió mientras Claude respondía la consulta %d: esa respuesta se descarta", self.pending.number)
        else:
            self._stable += 1
            if self.view_to_now is not None:
                self.view_to_now = step @ self.view_to_now
            if self.pending and self.pending.valid:
                self.pending.to_now = step @ self.pending.to_now

        if self._should_ask(width, height):
            self._ask(frame)
        if not self.boxes or self.view_to_now is None:
            return []
        return shapes_for((self.boxes, self.view_to_now), width, height)

    def ask_now(self) -> None:
        self._force = True

    def clear(self) -> None:
        self.boxes, self.view_to_now = [], None

    @property
    def status(self) -> str | None:
        if self.pending and self.pending.valid:
            return f"analizando… {self.clock() - self.pending.sent_at:.0f} s"
        if self._note and self.clock() < self._note[1]:
            return self._note[0]
        if self.queries >= self.max_queries:
            return f"tope de {self.max_queries} consultas"
        if self.failed:
            return "la IA no respondió"
        return None

    # --- consultas ---

    def _should_ask(self, width: int, height: int) -> bool:
        if (self.pending and self.pending.valid) or self.queries >= self.max_queries or self._stable < STABLE_FRAMES:
            return False
        if self._force:
            return True
        if self.clock() - self._last_query < self.every_s:
            return False
        return self.view_to_now is None or _overlap(self.view_to_now, width, height) < MIN_OVERLAP

    def _ask(self, frame: np.ndarray) -> None:
        self.queries += 1
        self._last_query, self._force = self.clock(), False
        path = self.work_dir / f"clave_{self.queries:03d}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        self.pending = _Pending(self.executor.submit(self.detector, path), self.queries, self.clock())
        logger.info("Consulta %d enviada a Claude", self.queries)

    def _collect(self) -> None:
        if not self.pending or not self.pending.future.done():
            return
        pending, self.pending = self.pending, None
        try:
            result = pending.future.result()
        except Exception:  # noqa: BLE001 (una consulta fallida no debe tumbar la pantalla)
            result = None
        elapsed = self.clock() - pending.sent_at
        self.failed = result is None
        if result is None:
            logger.warning("Consulta %d: la IA no respondió (%.1f s)", pending.number, elapsed)
        elif not pending.valid:
            # Pasa con videos que cambian de toma más rápido de lo que responde Claude (≈ 6 s).
            self._note = ("la toma cambió antes de la respuesta", self.clock() + NOTE_S)
        else:
            logger.info("Consulta %d: %d recuadros en %.1f s", pending.number, len(result), elapsed)
            self.boxes, self.view_to_now = result, pending.to_now


def _overlap(homography: np.ndarray, width: int, height: int) -> float:
    """Qué fracción de la imagen actual se veía en el último cuadro consultado."""
    rect = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    moved = cv2.perspectiveTransform(rect.reshape(-1, 1, 2), homography).reshape(-1, 2)
    if not np.isfinite(moved).all():
        return 0.0
    area, _ = cv2.intersectConvexConvex(rect, np.float32(moved))
    return float(area) / (width * height)


# ---------- Lectura de la fuente ----------


class _Reader(threading.Thread):
    """Lee la fuente en otro hilo y deja siempre el cuadro más reciente (así no se acumula retraso)."""

    def __init__(self, capture: cv2.VideoCapture, pace_fps: float | None) -> None:
        super().__init__(daemon=True)
        self.capture, self.pace_fps = capture, pace_fps
        self.lock = threading.Lock()
        self.frame, self.count = None, 0
        self.ended = self.stopped = self.paused = False

    def run(self) -> None:
        next_time = time.monotonic()
        while not self.stopped:
            if self.paused:
                time.sleep(0.03)
                next_time = time.monotonic()
                continue
            ok, frame = self.capture.read()
            if not ok:
                self.ended = True
                return
            with self.lock:
                self.frame, self.count = frame, self.count + 1
            if self.pace_fps:  # un video se reproduce a su velocidad real, no a la que alcance el PC
                next_time += 1 / self.pace_fps
                time.sleep(max(0.0, next_time - time.monotonic()))

    def latest(self) -> tuple[int, np.ndarray | None]:
        with self.lock:
            return self.count, self.frame


def _open_source(fuente: str) -> tuple[cv2.VideoCapture, bool]:
    if fuente.isdigit():
        capture = cv2.VideoCapture(int(fuente), cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(int(fuente))
        return capture, False
    is_file = Path(fuente).exists()
    capture = cv2.VideoCapture(str(Path(fuente).resolve()) if is_file else fuente, cv2.CAP_FFMPEG)
    return capture, is_file


def _fit(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if width > MAX_WIDTH:
        frame = cv2.resize(frame, (MAX_WIDTH, round(height * MAX_WIDTH / width) // 2 * 2), interpolation=cv2.INTER_AREA)
    return frame


# ---------- Grabación (opcional) ----------


class _Recorder:
    """Graba lo que se ve en pantalla, con el tiempo real de cada cuadro."""

    def __init__(self, path: Path, width: int, height: int) -> None:
        self.path, self.size = path, (width - width % 2, height - height % 2)
        self.process = subprocess.Popen(
            [find_ffmpeg(), "-y", "-loglevel", "error", "-use_wallclock_as_timestamps", "1", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-s", f"{self.size[0]}x{self.size[1]}", "-i", "-", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-fps_mode", "vfr", str(path)],
            stdin=subprocess.PIPE,
        )  # fmt: skip

    def write(self, image: Image.Image) -> None:
        if image.size != self.size:
            image = image.crop((0, 0, *self.size))
        self.process.stdin.write(image.tobytes())

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait()


# ---------- Comando ----------


def run_live(args, detector: Detector | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in ("httpx", "anthropic", "app.drone.boxes"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if detector is None:
        if not get_settings().ANTHROPIC_API_KEY:
            print("Falta ANTHROPIC_API_KEY en backend\\.env: se verá la imagen, pero sin recuadros.")
        effort = EFFORTS[args.esfuerzo]
        detector = lambda path: detect_buildings(path, effort=effort)

    capture, is_file = _open_source(args.fuente)
    if not capture.isOpened():
        print(f"No pude abrir la fuente {args.fuente!r}. Si es una cámara, prueba con otro número (0, 1, 2…).")
        return 1
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0

    print(f"Máximo {args.max_consultas} consultas a Claude (≈ USD {args.max_consultas * COST_PER_FRAME_USD:.2f}), una cada {args.cada:g} s como mínimo.")
    if not args.si and sys.stdin.isatty() and input("¿Sigo? (s/n): ").strip().lower() not in {"s", "si", "sí", "y"}:
        return 0

    work_dir = BACKEND_DIR / "data" / "vuelos" / f"vivo_{datetime.now():%Y%m%d_%H%M%S}"
    work_dir.mkdir(parents=True, exist_ok=True)
    session = LiveSession(detector, work_dir, every_s=args.cada, max_queries=args.max_consultas)
    reader = _Reader(capture, pace_fps=fps if is_file else None)
    reader.start()
    badge = "VIDEO GRABADO" if is_file else "EN VIVO"
    recorder = None
    if args.ventana:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        if args.pantalla_completa:
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    print("Teclas: Q o Esc salir · Espacio pausa · C preguntar ya · B borrar recuadros")

    seen = 0
    try:
        while True:
            count, frame = reader.latest()
            if reader.ended and count == seen:
                break
            if count == seen or frame is None:
                if not _keys(args, reader, session, wait_ms=5):
                    break
                continue
            seen = count
            frame = _fit(frame)
            shapes = session.process(frame)
            status = " · ".join(part for part in (badge, session.status) if part)
            image = draw_overlay(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), shapes, status)
            if args.grabar:
                recorder = recorder or _Recorder(Path(args.grabar).resolve(), *image.size)
                recorder.write(image)
            if args.ventana:
                cv2.imshow(WINDOW, cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
                if not _keys(args, reader, session, wait_ms=1):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        reader.stopped = True
        reader.join(timeout=1)
        capture.release()
        if recorder:
            recorder.close()
            print(f"Grabación: {recorder.path}")
        if args.ventana:
            cv2.destroyAllWindows()
        session.executor.shutdown(wait=False, cancel_futures=True)
    print(f"Consultas a Claude: {session.queries}. Cuadros enviados en {work_dir}")
    return 0


def _keys(args, reader: _Reader, session: LiveSession, wait_ms: int) -> bool:
    """Atiende el teclado. Devuelve False si hay que salir."""
    if not args.ventana:
        if wait_ms > 1:
            time.sleep(wait_ms / 1000)
        return True
    key = cv2.waitKey(wait_ms) & 0xFF
    if key in (ord("q"), ord("Q"), 27):
        return False
    if key == ord(" "):
        reader.paused = not reader.paused
    elif key in (ord("c"), ord("C")):
        session.ask_now()
    elif key in (ord("b"), ord("B")):
        session.clear()
    try:
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1  # cerraron la ventana con la X
    except cv2.error:
        return False


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.drone.live", description=__doc__.split("\n\n")[0])
    p.add_argument("--fuente", default="0", help="número de cámara (0, 1…), ruta de un video o URL rtmp:// (0)")
    p.add_argument("--cada", type=float, default=4.0, help="segundos mínimos entre consultas a Claude (4)")
    p.add_argument("--max-consultas", type=int, default=40, help="tope de consultas por sesión, por el presupuesto (40)")
    p.add_argument("--esfuerzo", choices=list(EFFORTS), default="bajo", help="cuánto piensa el modelo (bajo)")
    p.add_argument("--modelo", help="otro modelo de Claude, p. ej. uno más rápido (por defecto, VISION_MODEL del .env)")
    p.add_argument("--pantalla-completa", action="store_true", help="abrir la ventana en pantalla completa")
    p.add_argument("--grabar", help="guardar lo que se ve en un .mp4 (respaldo para la expo)")
    p.add_argument("--sin-ventana", dest="ventana", action="store_false", help="no mostrar ventana (con --grabar)")
    p.add_argument("--si", action="store_true", help="no preguntar antes de gastar")
    return p


if __name__ == "__main__":
    sys.exit(run_live(_parser().parse_args()))
