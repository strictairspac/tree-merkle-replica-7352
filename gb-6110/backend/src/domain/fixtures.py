from itertools import cycle


def _reference():
    streets = cycle(["槐河路", "栖霞巷", "东砖街"])
    return [
        {"tree": tree, "street": next(streets), "status": "巡检完成", "revision": 2}
        for tree in range(1233, 1281)
    ]


def _replica(reference):
    replica = [{**row} for row in reference if row["tree"] != 1259]
    next(row for row in replica if row["tree"] == 1234).update(status="待扶正", revision=1)
    next(row for row in replica if row["tree"] == 1260).update(status="待复验")
    replica.append({"tree": 1281, "street": "东砖街", "status": "待修枝", "revision": 1})
    return list(reversed(replica))


REFERENCE = _reference()
FIXTURES = [
    {
        "code": "ST-XH-1124",
        "title": "西河片区晨班副本点验",
        "description": "核对 48 株现场巡检副本，定位旧版、缺株、孤立行与同版冲突。",
        "payload": {
            "epoch": "2026-11-24T08:40+08:00",
            "replica_epoch": "2026-11-24T08:40+08:00",
            "reference": REFERENCE,
            "replica": _replica(REFERENCE),
        },
    },
    {
        "code": "ST-DC-1124",
        "title": "东城调序后保持一致",
        "description": "终端将同一快照按逆序导出，两边的 Merkle 根仍然一致。",
        "payload": {
            "epoch": "2026-11-24T09:15+08:00",
            "replica_epoch": "2026-11-24T09:15+08:00",
            "reference": REFERENCE[:6],
            "replica": list(reversed(REFERENCE[:6])),
        },
    },
]
