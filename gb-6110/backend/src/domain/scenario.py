from datetime import datetime

from .fixtures import FIXTURES
from .merkle import EMPTY, KeyTree, compare
from .snapshot import parse_snapshot


CONFIG = {
    "title": "青徊园护·行道树副本点验",
    "team": "青徊园护 12 人行道树巡养与离线数据组",
    "description": "巡养终端回网后先比较整段摘要，仅展开存在差异的树号区间。",
    "direction": "副本反熵与 Merkle 区间比对",
    "mechanism": "共享主键边界的稀疏 Merkle 树，按区间展开缺行、孤立行和不同版本。",
    "modules": ["巡护交班", "双侧养护快照", "分段点验", "补录核查单", "副本补传"],
    "unit": "副本点验批",
    "max_parameter": 65536,
    "parameter_label": "每个叶区间包含的树号数（1–65536）",
    "default_parameter": 16,
    "facts": ["差异区间", "差异树木", "比较摘要"],
    "palette": 10,
    "fixture": "ST-XH-1124 / 西河片区",
}


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError("输入需为对象")
    try:
        epochs = [datetime.fromisoformat(payload.get(key, "")) for key in ("epoch", "replica_epoch")]
        if any(epoch.utcoffset() is None for epoch in epochs):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("epoch 和 replica_epoch 须为带时区的 ISO 8601 时间") from None
    if epochs[0] != epochs[1]:
        raise ValueError("两侧基准时间不同，先导出同一水位的养护快照")
    return parse_snapshot(payload.get("reference"), "reference"), parse_snapshot(payload.get("replica"), "replica")


def validate(payload):
    normalize(payload)


def classify(reference, replica):
    if not reference:
        return "副本多行"
    if not replica:
        return "副本缺行"
    if replica.revision < reference.revision:
        return "副本版本落后"
    if replica.revision > reference.revision:
        return "副本版本超前"
    return "同代内容冲突"


def run(payload, parameter, db):
    official, field = normalize(payload)
    largest_key = max(max(official, default=1), max(field, default=1))
    leaf_count = 1 << ((largest_key - 1) // parameter).bit_length()
    reference = KeyTree(official, parameter, leaf_count)
    replica = KeyTree(field, parameter, leaf_count)
    comparison = compare(reference, replica)
    rows = []
    drift = 0
    for index, official_hash, replica_hash in comparison.windows:
        interval = f"{index * parameter + 1}–{(index + 1) * parameter}"
        left = {entry.tree: entry for entry in reference.bins.get(index, ())}
        right = {entry.tree: entry for entry in replica.bins.get(index, ())}
        for tree in sorted(left.keys() | right.keys()):
            a, b = left.get(tree), right.get(tree)
            if a == b:
                continue
            drift += 1
            rows.append({
                "区间": interval, "树号": tree, "结论": classify(a, b),
                "主侧记录": a.text() if a else None, "副侧记录": b.text() if b else None,
                "主侧摘要": official_hash, "副侧摘要": replica_hash,
            })
    if not rows:
        rows.append({
            "区间": f"1–{leaf_count * parameter}", "树号": None, "结论": "根摘要一致",
            "主侧记录": f"{len(official)} 条", "副侧记录": f"{len(field)} 条",
            "主侧摘要": reference.levels[-1].get(0, EMPTY).hex(),
            "副侧摘要": replica.levels[-1].get(0, EMPTY).hex(),
        })
    return {
        "summary": f"检查 {comparison.checked} 个节点摘要，{len(comparison.windows)} 个区间有差异。",
        "metrics": {"差异区间": len(comparison.windows), "差异树木": drift,
                    "比较摘要": comparison.checked, "跳过叶区间": comparison.spared_leaves,
                    "总叶区间": leaf_count},
        "rows": rows,
    }
