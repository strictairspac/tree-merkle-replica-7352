"""巡养副本补传的服务层验收：分段乱序、一次性切换、同底合流、整批退回、派单钉版。

运行方式（backend 目录下）：python -m pytest tests/ -q 或 python tests/test_replica_sync.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DEMO_PASSWORD", "test-password")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402

from src.constants.job_state import BatchState, JobState  # noqa: E402
from src.models import audit, cases, replica, reviews, runs, users  # noqa: E402,F401
from src.models.base import metadata  # noqa: E402
from src.models.runs import runs as runs_table  # noqa: E402
from src.schemas.cases import CaseInput  # noqa: E402
from src.schemas.sync import BatchInput, SegmentInput  # noqa: E402
from src.services import cases as cases_service  # noqa: E402
from src.services import execution, replica as store, runs as runs_service  # noqa: E402

EPOCH = "2026-11-24T08:40+08:00"


def sample_payload(replica_rows, reference_rows=None):
    return {
        "epoch": EPOCH,
        "replica_epoch": EPOCH,
        "reference": reference_rows if reference_rows is not None else [
            {"tree": 10, "street": "槐河路", "status": "巡检完成", "revision": 2},
            {"tree": 20, "street": "栖霞巷", "status": "待修枝", "revision": 2},
            {"tree": 30, "street": "东砖街", "status": "巡检完成", "revision": 2},
        ],
        "replica": replica_rows,
    }


def base_rows():
    return [
        {"tree": 10, "street": "槐河路", "status": "巡检完成", "revision": 2},
        {"tree": 20, "street": "栖霞巷", "status": "巡检完成", "revision": 1},
        {"tree": 30, "street": "东砖街", "status": "巡检完成", "revision": 2},
    ]


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db")
        metadata.create_all(self.engine)
        with self.engine.begin() as db:
            form = CaseInput(title="西河片区点验", description="", payload=sample_payload(base_rows()))
            self.case = cases_service.create(db, form, "operator")

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def open_batch(self, db, segments=2, base=1, epoch=EPOCH):
        return store.open_batch(db, self.case["id"], BatchInput(epoch=epoch, base_version=base, segments=segments), "operator")

    def upload(self, db, batch_id, segment, changes):
        return store.upload_segment(db, self.case["id"], batch_id, SegmentInput(segment=segment, changes=changes), "operator")

    def entries(self, db, version):
        return {row["tree"]: row for row in store.entries_at(db, self.case["id"], version)}

    def test_case_creation_initializes_v1_and_enqueue_pins_it(self):
        with self.engine.begin() as db:
            self.assertEqual(store.current_version(db, self.case["id"]), 1)
            self.assertEqual(len(self.entries(db, 1)), 3)
            run = runs_service.enqueue(db, self.case["id"], 16, "operator")
            self.assertEqual(run["replica_version"], 1)

    def test_out_of_order_segments_and_atomic_switch(self):
        with self.engine.begin() as db:
            batch = self.open_batch(db, segments=3)
            self.assertEqual(batch["state"], BatchState.RECEIVING)
            # 分段乱序到达：3、1 先到，批次仍在接收中，版本不切换。
            state = self.upload(db, batch["id"], 3, [{"tree": 30, "removed": True}])
            self.assertEqual(state["state"], BatchState.RECEIVING)
            state = self.upload(db, batch["id"], 1, [
                {"tree": 10, "street": "槐河路", "status": "待扶正", "revision": 3},
            ])
            self.assertEqual(state["state"], BatchState.RECEIVING)
            self.assertEqual(state["arrived"], [1, 3])
            # 收齐前：当前版本仍是 v1，新派单的点验照旧钉旧版。
            self.assertEqual(store.current_version(db, self.case["id"]), 1)
            queued = runs_service.enqueue(db, self.case["id"], 16, "operator")
            self.assertEqual(queued["replica_version"], 1)
            self.assertEqual(self.entries(db, 1)[30]["status"], "巡检完成")
            # 最后一个分段到达，一次性切换到 v2。
            state = self.upload(db, batch["id"], 2, [
                {"tree": 40, "street": "东砖街", "status": "待修枝", "revision": 1},
            ])
            self.assertEqual(state["state"], BatchState.APPLIED)
            self.assertEqual(state["applied_version"], 2)
            self.assertEqual(store.current_version(db, self.case["id"]), 2)
            merged = self.entries(db, 2)
            self.assertEqual(merged[10]["status"], "待扶正")
            self.assertNotIn(30, merged)
            self.assertEqual(merged[40]["street"], "东砖街")
            self.assertEqual(len(self.entries(db, 1)), 3)  # 旧版保持可读
            later = runs_service.enqueue(db, self.case["id"], 16, "operator")
            self.assertEqual(later["replica_version"], 2)

    def test_concurrent_batches_on_same_base_both_survive(self):
        with self.engine.begin() as db:
            first = self.open_batch(db, segments=1)
            second = self.open_batch(db, segments=1)
            # 两批同底，改动不同树号：都保留。
            done = self.upload(db, first["id"], 1, [
                {"tree": 10, "street": "槐河路", "status": "待扶正", "revision": 3},
            ])
            self.assertEqual(done["state"], BatchState.APPLIED)
            self.assertEqual(done["applied_version"], 2)
            done = self.upload(db, second["id"], 1, [
                {"tree": 20, "street": "栖霞巷", "status": "待复验", "revision": 4},
            ])
            self.assertEqual(done["state"], BatchState.APPLIED)
            self.assertEqual(done["applied_version"], 3)
            merged = self.entries(db, 3)
            self.assertEqual(merged[10]["status"], "待扶正")
            self.assertEqual(merged[20]["status"], "待复验")

    def test_conflicting_batch_is_rejected_wholesale_and_removal_counts(self):
        with self.engine.begin() as db:
            first = self.open_batch(db, segments=1)
            second = self.open_batch(db, segments=1)
            # 第一批移除 30、改动 10。
            done = self.upload(db, first["id"], 1, [
                {"tree": 30, "removed": True},
                {"tree": 10, "street": "槐河路", "status": "待扶正", "revision": 3},
            ])
            self.assertEqual(done["state"], BatchState.APPLIED)
            # 第二批动到对方移除过的 30：整批退回，其余不相干的改动也不生效。
            rejected = self.upload(db, second["id"], 1, [
                {"tree": 30, "street": "东砖街", "status": "巡检完成", "revision": 3},
                {"tree": 40, "street": "栖霞巷", "status": "待修枝", "revision": 1},
            ])
            self.assertEqual(rejected["state"], BatchState.REJECTED)
            self.assertIn("30", rejected["failure"])
            self.assertEqual(store.current_version(db, self.case["id"]), 2)
            self.assertNotIn(40, self.entries(db, 2))
            # 改动对方改过的 10 同样退回；墓碑与更新都算改动。
            third = self.open_batch(db, segments=1, base=1)
            rejected = self.upload(db, third["id"], 1, [
                {"tree": 10, "street": "槐河路", "status": "巡检完成", "revision": 5},
            ])
            self.assertEqual(rejected["state"], BatchState.REJECTED)
            # 不相交的批次照常应用。
            fourth = self.open_batch(db, segments=1, base=1)
            done = self.upload(db, fourth["id"], 1, [
                {"tree": 20, "street": "栖霞巷", "status": "待复验", "revision": 4},
            ])
            self.assertEqual(done["state"], BatchState.APPLIED)

    def test_duplicate_tree_inside_batch_is_rejected(self):
        with self.engine.begin() as db:
            batch = self.open_batch(db, segments=2)
            self.upload(db, batch["id"], 1, [{"tree": 10, "street": "槐河路", "status": "待扶正", "revision": 3}])
            state = self.upload(db, batch["id"], 2, [{"tree": 10, "removed": True}])
            self.assertEqual(state["state"], BatchState.REJECTED)
            self.assertIn("重复", state["failure"])
            self.assertEqual(store.current_version(db, self.case["id"]), 1)

    def test_input_validation(self):
        with self.engine.begin() as db:
            with self.assertRaises(HTTPException) as ctx:
                self.open_batch(db, epoch="2026-11-24T09:00+08:00")
            self.assertEqual(ctx.exception.status_code, 422)
            with self.assertRaises(HTTPException) as ctx:
                self.open_batch(db, base=9)
            self.assertEqual(ctx.exception.status_code, 422)
            batch = self.open_batch(db, segments=2)
            with self.assertRaises(HTTPException) as ctx:
                self.upload(db, batch["id"], 3, [])
            self.assertEqual(ctx.exception.status_code, 422)
            with self.assertRaises(HTTPException) as ctx:
                self.upload(db, batch["id"], 1, [{"tree": 10, "status": "待扶正", "revision": 3}])
            self.assertEqual(ctx.exception.status_code, 422)
            self.upload(db, batch["id"], 1, [{"tree": 10, "removed": True}])
            with self.assertRaises(HTTPException) as ctx:
                self.upload(db, batch["id"], 1, [{"tree": 20, "removed": True}])
            self.assertEqual(ctx.exception.status_code, 409)
            state = self.upload(db, batch["id"], 2, [])
            self.assertEqual(state["state"], BatchState.APPLIED)
            with self.assertRaises(HTTPException) as ctx:
                self.upload(db, batch["id"], 2, [])
            self.assertEqual(ctx.exception.status_code, 409)

    def test_queued_run_executes_on_dispatch_version(self):
        with self.engine.begin() as db:
            queued = runs_service.enqueue(db, self.case["id"], 16, "operator")
            batch = self.open_batch(db, segments=1)
            # 切换后副本与主账一致；但已排队的点验仍按派单时的 v1 执行。
            self.upload(db, batch["id"], 1, [
                {"tree": 20, "street": "栖霞巷", "status": "待修枝", "revision": 2},
            ])
            self.assertEqual(store.current_version(db, self.case["id"]), 2)
        original_engine = execution.engine
        execution.engine = self.engine
        try:
            self.assertTrue(execution.service_one())
        finally:
            execution.engine = original_engine
        with self.engine.connect() as db:
            row = db.execute(select(runs_table).where(runs_table.c.id == queued["id"])).mappings().first()
            self.assertEqual(row["status"], JobState.DONE)
            self.assertEqual(row["replica_version"], 1)
            result = row["result"]
            self.assertEqual(result["replica_version"], 1)
            self.assertEqual(result["metrics"]["副本版本"], "v1")
            drift = {line["树号"]: line["结论"] for line in result["rows"]}
            self.assertEqual(drift.get(20), "副本版本落后")


if __name__ == "__main__":
    unittest.main()
