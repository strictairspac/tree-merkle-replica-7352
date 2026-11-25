from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Integer, String, Table, UniqueConstraint
from .base import metadata


replica_versions = Table(
    "replica_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("source", String(16), nullable=False),
    Column("batch_id", Integer, nullable=True),
    Column("entries", Integer, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("case_id", "version"),
)

replica_entries = Table(
    "replica_entries", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("tree", Integer, nullable=False),
    Column("street", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("revision", Integer, nullable=False),
    UniqueConstraint("case_id", "version", "tree"),
)

sync_batches = Table(
    "sync_batches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("base_version", Integer, nullable=False),
    Column("segments", Integer, nullable=False),
    Column("state", String(16), nullable=False, index=True),
    Column("touched", JSON(none_as_null=True), nullable=True),
    Column("applied_version", Integer, nullable=True),
    Column("failure", String(320), nullable=True),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger, nullable=True),
)

sync_segments = Table(
    "sync_segments", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", ForeignKey("sync_batches.id"), nullable=False, index=True),
    Column("segment", Integer, nullable=False),
    Column("changes", JSON, nullable=False),
    Column("received_at", BigInteger, nullable=False),
    UniqueConstraint("batch_id", "segment"),
)
