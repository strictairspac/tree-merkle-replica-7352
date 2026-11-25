from pydantic import BaseModel, Field

from src.constants.job_state import BatchState
from src.services.replica import MAX_BATCH_CHANGES, MAX_SEGMENTS


class BatchInput(BaseModel):
    epoch: str = Field(min_length=8, max_length=40)
    base_version: int = Field(strict=True, ge=1)
    segments: int = Field(strict=True, ge=1, le=MAX_SEGMENTS)


class SegmentInput(BaseModel):
    segment: int = Field(strict=True, ge=1)
    changes: list[dict] = Field(max_length=MAX_BATCH_CHANGES)


class BatchEntry(BaseModel):
    id: int
    case_id: int
    base_version: int
    segments: int
    received: int
    state: BatchState
    applied_version: int | None
    failure: str | None
    touched: list[int] | None
    actor: str
    created_at: int
    finished_at: int | None


class BatchDetail(BatchEntry):
    arrived: list[int]


class ReplicaStatus(BaseModel):
    case_id: int
    version: int | None
    entries: int | None
