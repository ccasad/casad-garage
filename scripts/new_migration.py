"""Generate an Alembic migration against an empty SQLite database (no Postgres needed).

uv run python scripts/new_migration.py "describe the change"
"""

import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

config = Config("alembic.ini")
with create_engine("sqlite://").begin() as connection:
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    command.revision(config, message=sys.argv[1], autogenerate=True)
