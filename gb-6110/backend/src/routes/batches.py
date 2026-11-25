from fastapi import APIRouter, Depends

from src.config.resources import engine
from src.controllers.access import identity, operator
from src.controllers.workbench import new_batch, new_segment
from src.schemas.sync import BatchDetail, BatchEntry, BatchInput, ReplicaStatus, SegmentInput
from src.services import replica

router = APIRouter(prefix="/cases", tags=["Replica Sync"])


@router.get("/{case_id}/replica", response_model=ReplicaStatus, dependencies=[Depends(identity)])
def replica_status(case_id: int):
    with engine.connect() as db:
        return replica.status(db, case_id)


@router.get("/{case_id}/batches", response_model=list[BatchEntry], dependencies=[Depends(identity)])
def list_batches(case_id: int):
    with engine.connect() as db:
        return replica.list_batches(db, case_id)


@router.post("/{case_id}/batches", response_model=BatchEntry, status_code=201)
def open(case_id: int, form: BatchInput, user=Depends(operator)):
    return new_batch(case_id, form, user)


@router.get("/{case_id}/batches/{batch_id}", response_model=BatchDetail, dependencies=[Depends(identity)])
def batch_detail(case_id: int, batch_id: int):
    with engine.connect() as db:
        return replica.get_batch(db, case_id, batch_id)


@router.post("/{case_id}/batches/{batch_id}/segments", response_model=BatchEntry, status_code=201)
def upload(case_id: int, batch_id: int, form: SegmentInput, user=Depends(operator)):
    return new_segment(case_id, batch_id, form, user)
