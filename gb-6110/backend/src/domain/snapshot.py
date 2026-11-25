import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    tree: int
    street: str
    status: str
    revision: int

    def text(self):
        return f"{self.street}｜{self.status}｜v{self.revision}"

    def canonical(self):
        return json.dumps(
            [self.tree, self.street, self.status, self.revision],
            ensure_ascii=False, separators=(",", ":"),
        ).encode()


STATUS = {"巡检完成", "待修枝", "待扶正", "待复验"}


def parse_snapshot(rows, name):
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError(f"{name} 须为最多 2000 条树木养护记录")
    snapshot = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("养护记录必须是对象")
        tree, street, status, revision = (row.get(key) for key in ("tree", "street", "status", "revision"))
        if type(tree) is not int or not 1 <= tree <= 10_000_000:
            raise ValueError("树木编号须为 1 至 10000000 的整数")
        if tree in snapshot:
            raise ValueError(f"{name} 有重复树木主键：{tree}")
        if not isinstance(street, str) or not re.fullmatch(r"[^\x00-\x1f\ud800-\udfff]{1,32}", street):
            raise ValueError("路段需要 1 至 32 位合法字符")
        if not isinstance(status, str) or status not in STATUS:
            raise ValueError("状态须为巡检完成、待修枝、待扶正或待复验")
        if type(revision) is not int or not 1 <= revision <= 1_000_000:
            raise ValueError("修订号须为 1 至 1000000")
        snapshot[tree] = Entry(tree, street, status, revision)
    return snapshot
