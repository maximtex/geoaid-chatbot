from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db import models  # noqa: F401  (registra las tablas en Base.metadata)
from app.db.database import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL siempre sale del .env (DATABASE_URL), nunca de alembic.ini.
DATABASE_URL = get_settings().DATABASE_URL
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            # render_as_batch: SQLite no soporta ALTER TABLE completo; Alembic recrea la tabla.
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
