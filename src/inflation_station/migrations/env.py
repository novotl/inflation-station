from typing import Any, Literal

from alembic import context
from sqlalchemy.types import TypeDecorator

from inflation_station.settings import Settings
from inflation_station.store import Base, database_url, engine


def render_item(type_: str, obj: Any, _autogen_context: Any) -> str | Literal[False]:  # noqa: ANN401 - Alembic hook signature
    # Migrations spell custom types as their storage type, so they never import application code.
    if type_ == "type" and isinstance(obj, TypeDecorator):
        return f"sa.{obj.impl_instance!r}"
    return False


# store.migrate passes its database; the `alembic` dev CLI falls back to the configured one.
url = context.config.attributes.get("url") or database_url(Settings().data_dir)
with engine(url).connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite can't ALTER most things; batch mode copies the table instead
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()
