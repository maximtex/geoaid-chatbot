import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from app.api.public import router as public_router
from app.bot.meta_client import MetaClient
from app.bot.router import router as whatsapp_router
from app.bot.state_manager import Bot, MessagingClient
from app.config import Settings, get_settings
from app.db.database import make_engine, make_session_factory

logger = logging.getLogger("app")


def create_app(
    settings: Settings | None = None,
    client: MessagingClient | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)

    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.DATABASE_URL))
    owned_client = MetaClient(settings) if client is None else None
    client = client or owned_client

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not settings.WHATSAPP_APP_SECRET:
            logger.warning("WHATSAPP_APP_SECRET vacío: no se validará la firma de Meta (solo aceptable en DEBUG)")
        settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        yield
        if owned_client is not None:
            await owned_client.aclose()

    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.bot = Bot(settings=settings, client=client, session_factory=session_factory)
    app.include_router(whatsapp_router, prefix=settings.API_V1_STR)
    app.include_router(public_router, prefix=settings.API_V1_STR)
    # Solo lectura para la web del equipo. El encabezado de ngrok gratis debe permitirse en el preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["ngrok-skip-browser-warning", "Content-Type"],
    )

    @app.get("/health", tags=["Sistema"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
