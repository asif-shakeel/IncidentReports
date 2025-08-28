# alembic/env.py (top of file)
import os, sys
from logging.config import fileConfig
from alembic import context

# Add project root to sys.path so 'app' is importable when running alembic anywhere
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from sqlalchemy import engine_from_config, pool


import sys
import os
from dotenv import load_dotenv
import os
from pathlib import Path

root_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=root_env, override=True) 

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from main import Base
from app.database import engine
from app.models import Base

# Alembic Config object
config = context.config

# Setup logging
fileConfig(config.config_file_name)

# Metadata for 'autogenerate'
target_metadata = Base.metadata

def get_url():
    return os.getenv("DATABASE_URL")

def run_migrations_offline():
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        {},
        url=get_url(),
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
