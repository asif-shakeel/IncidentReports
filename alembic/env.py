# alembic/env.py
from __future__ import annotations
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context


# Interpret the config file for Python logging.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 1) DATABASE_URL from env (Render & local)
database_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_SYNC") or ""

if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# 2) import your Base metadata
from app.database import Base  # Base = declarative_base() used by your models
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),  # reads sqlalchemy.url
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
