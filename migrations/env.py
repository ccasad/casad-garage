from logging.config import fileConfig

from alembic import context

from app.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


# Tests pass in their own connection; otherwise use DATABASE_URL.
connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    from app.db import get_engine

    with get_engine().connect() as connection:
        run_migrations(connection)
