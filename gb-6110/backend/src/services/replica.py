from time import time

from fastapi import HTTPException
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.constants.job_state import BatchState
from src.domain.snapshot import parse_change, parse_snapshot
from src.models.cases import cases
from src.models.replica import replica_entries, replica_versions, sync_batches, sync_segments
from . import audit

MAX_BATCH_CHANGES = 2000
MAX_SEGMENTS = 64


def lock_case(db, case_id):
    """锁定资料行：补传收口、版本初始化与并发提交都沿此串行。"""
    row = db.execute(
        select(cases.c.id, cases.c.payload).where(cases.c.id == case_id).with_for_update()
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "资料不存在")
    return row


def current_version(db, case_id):
    return db.scalar(select(func.max(replica_versions.c.version)).where(replica_versions.c.case_id == case_id))


def initialize(db, case_id, payload):
    """以资料中的终端快照建立 v1；已存在版本库时直接返回当前版本。"""
    version = current_version(db, case_id)
    if version is not None:
        return version
    snapshot = parse_snapshot((payload or {}).get("replica"), "replica")
    db.execute(insert(replica_versions).values(
        case_id=case_id, version=1, source="initial", batch_id=None, entries=len(snapshot), created_at=int(time()),
    ))
    if snapshot:
        db.execute(insert(replica_entries), [
            {"case_id": case_id, "version": 1, "tree": entry.tree, "street": entry.street,
             "status": entry.status, "revision": entry.revision}
            for entry in snapshot.values()
        ])
    return 1


def ensure_store(db, case_id, payload):
    """在持有资料行锁的事务里确保版本库存在；快照无效时返回 None。"""
    version = current_version(db, case_id)
    if version is None and payload is not None:
        try:
            version = initialize(db, case_id, payload)
        except ValueError:
            version = None
    return version


def entry_rows(db, case_id, version):
    return db.execute(
        select(replica_entries)
        .where(replica_entries.c.case_id == case_id, replica_entries.c.version == version)
        .order_by(replica_entries.c.tree)
    ).mappings().all()


def entries_at(db, case_id, version):
    """点验执行用：取出指定版本的完整副本，还原为快照字典列表。"""
    exists = db.scalar(
        select(replica_versions.c.id)
        .where(replica_versions.c.case_id == case_id, replica_versions.c.version == version)
    )
    if exists is None:
        raise ValueError(f"副本版本 v{version} 不存在")
    return [
        {"tree": row["tree"], "street": row["street"], "status": row["status"], "revision": row["revision"]}
        for row in entry_rows(db, case_id, version)
    ]


def status(db, case_id):
    if db.scalar(select(cases.c.id).where(cases.c.id == case_id)) is None:
        raise HTTPException(404, "资料不存在")
    version = current_version(db, case_id)
    entries = None
    if version is not None:
        entries = db.scalar(
            select(replica_versions.c.entries)
            .where(replica_versions.c.case_id == case_id, replica_versions.c.version == version)
        )
    return {"case_id": case_id, "version": version, "entries": entries}


def open_batch(db, case_id, data, actor):
    case = lock_case(db, case_id)
    version = ensure_store(db, case_id, case["payload"])
    if version is None:
        raise HTTPException(422, "资料中的终端快照无法作为初始副本版本")
    if data.base_version > version:
        raise HTTPException(422, f"底版 v{data.base_version} 不存在，当前副本为 v{version}")
    epoch = (case["payload"] or {}).get("replica_epoch")
    if epoch and data.epoch != epoch:
        raise HTTPException(422, "补传截止时点与资料的 replica_epoch 不一致")
    change = db.execute(insert(sync_batches).values(
        case_id=case_id, base_version=data.base_version, segments=data.segments,
        state=BatchState.RECEIVING, actor=actor, created_at=int(time()),
    ))
    batch_id = change.inserted_primary_key[0]
    audit.record(db, "open_batch", actor, "batch", batch_id)
    return get_batch(db, case_id, batch_id)


def upload_segment(db, case_id, batch_id, data, actor):
    """分段乱序到达；收齐全部分段后在同一事务里一次性切换或整批退回。"""
    lock_case(db, case_id)
    batch = db.execute(
        select(sync_batches).where(sync_batches.c.id == batch_id, sync_batches.c.case_id == case_id)
    ).mappings().first()
    if batch is None:
        raise HTTPException(404, "补传批次不存在")
    if batch["state"] != BatchState.RECEIVING:
        raise HTTPException(409, "补传批次已收口，不再接收分段")
    if not 1 <= data.segment <= batch["segments"]:
        raise HTTPException(422, f"分段序号须在 1 到 {batch['segments']} 之间")
    try:
        for row in data.changes:
            parse_change(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        db.execute(insert(sync_segments).values(
            batch_id=batch_id, segment=data.segment, changes=data.changes, received_at=int(time()),
        ))
    except IntegrityError as exc:
        raise HTTPException(409, f"分段 {data.segment} 已收到") from exc
    arrived = db.scalar(select(func.count()).select_from(sync_segments).where(sync_segments.c.batch_id == batch_id))
    if arrived >= batch["segments"]:
        finalize(db, case_id, batch, actor)
    return get_batch(db, case_id, batch_id)


def describe(trees):
    ordered = sorted(trees)
    shown = "、".join(str(tree) for tree in ordered[:8])
    return f"{shown} 等 {len(ordered)} 个" if len(ordered) > 8 else shown


def finalize(db, case_id, batch, actor):
    now = int(time())
    rows = db.execute(
        select(sync_segments).where(sync_segments.c.batch_id == batch["id"]).order_by(sync_segments.c.segment)
    ).mappings().all()
    changes = {}
    duplicates = set()
    total = 0
    for row in rows:
        for raw in row["changes"]:
            change = parse_change(raw)
            total += 1
            if change.tree in changes:
                duplicates.add(change.tree)
            changes[change.tree] = change
    touched = sorted(changes)

    def reject(reason):
        db.execute(update(sync_batches).where(sync_batches.c.id == batch["id"]).values(
            state=BatchState.REJECTED, touched=touched, failure=reason[:320], finished_at=now,
        ))
        audit.record(db, "reject_batch", actor, "batch", batch["id"])

    if duplicates:
        return reject(f"同一补传批次内树号重复：{describe(duplicates)}")
    if total > MAX_BATCH_CHANGES:
        return reject(f"单批补传变更不能超过 {MAX_BATCH_CHANGES} 条")
    # 底版之后已应用的补传所触碰的树号（含移除）都与本批互斥。
    others = db.execute(select(sync_batches.c.touched).where(
        sync_batches.c.case_id == case_id,
        sync_batches.c.state == BatchState.APPLIED,
        sync_batches.c.applied_version > batch["base_version"],
    )).scalars().all()
    taken = set()
    for trees in others:
        taken.update(trees or ())
    conflicts = taken.intersection(touched)
    if conflicts:
        return reject(f"树号已被其他补传批次改动：{describe(conflicts)}")
    version = current_version(db, case_id)
    merged = {
        row["tree"]: {"tree": row["tree"], "street": row["street"], "status": row["status"], "revision": row["revision"]}
        for row in entry_rows(db, case_id, version)
    }
    for tree, change in changes.items():
        if change.entry is None:
            merged.pop(tree, None)
        else:
            merged[tree] = {"tree": tree, "street": change.entry.street,
                            "status": change.entry.status, "revision": change.entry.revision}
    new_version = version + 1
    db.execute(insert(replica_versions).values(
        case_id=case_id, version=new_version, source="batch", batch_id=batch["id"],
        entries=len(merged), created_at=now,
    ))
    if merged:
        db.execute(insert(replica_entries), [
            {"case_id": case_id, "version": new_version, **merged[tree]} for tree in sorted(merged)
        ])
    db.execute(update(sync_batches).where(sync_batches.c.id == batch["id"]).values(
        state=BatchState.APPLIED, touched=touched, applied_version=new_version, finished_at=now,
    ))
    audit.record(db, "apply_batch", actor, "batch", batch["id"])


def get_batch(db, case_id, batch_id):
    batch = db.execute(
        select(sync_batches).where(sync_batches.c.id == batch_id, sync_batches.c.case_id == case_id)
    ).mappings().first()
    if batch is None:
        raise HTTPException(404, "补传批次不存在")
    arrived = db.execute(
        select(sync_segments.c.segment).where(sync_segments.c.batch_id == batch_id).order_by(sync_segments.c.segment)
    ).scalars().all()
    return {**dict(batch), "received": len(arrived), "arrived": list(arrived)}


def list_batches(db, case_id):
    if db.scalar(select(cases.c.id).where(cases.c.id == case_id)) is None:
        raise HTTPException(404, "资料不存在")
    statement = (
        select(sync_batches, func.count(sync_segments.c.id).label("received"))
        .outerjoin(sync_segments, sync_segments.c.batch_id == sync_batches.c.id)
        .where(sync_batches.c.case_id == case_id)
        .group_by(sync_batches.c.id)
        .order_by(sync_batches.c.id.desc())
        .limit(100)
    )
    return [dict(row) for row in db.execute(statement).mappings()]
