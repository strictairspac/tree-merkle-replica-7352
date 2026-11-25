from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    DONE = "done"
    FAILED = "failed"


class BatchState(StrEnum):
    RECEIVING = "receiving"
    APPLIED = "applied"
    REJECTED = "rejected"
