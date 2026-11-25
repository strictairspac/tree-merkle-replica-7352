from sqlalchemy import inspect, select, text

from src.models import audit, cases, replica, reviews, runs, users  # Register the tables.
from src.models.base import metadata
from src.models.cases import cases as cases_table
from src.services.replica import initialize


def upgrade(connection):
    # Version 2 adds the versioned replica store and pins runs to a replica version.
    metadata.create_all(connection)
    columns = {column["name"] for column in inspect(connection).get_columns("runs")}
    if "replica_version" not in columns:
        connection.execute(text("ALTER TABLE runs ADD COLUMN replica_version INTEGER NULL"))
    # 既有资料以 payload 中的终端快照补建 v1；快照无效的资料保持无版本库，按原逻辑执行。
    for row in connection.execute(select(cases_table.c.id, cases_table.c.payload)).mappings():
        try:
            initialize(connection, row["id"], row["payload"])
        except ValueError:
            continue
