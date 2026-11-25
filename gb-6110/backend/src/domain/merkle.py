from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256


EMPTY = sha256(b"empty").digest()


def leaf_hash(entries):
    return sha256(b"leaf:" + b"\0".join(entry.canonical() for entry in entries)).digest()


def bundle(lower, upper):
    if lower == upper == EMPTY:
        return EMPTY
    return sha256(b"branch:" + lower + upper).digest()


class KeyTree:
    def __init__(self, snapshot, width, leaf_count):
        self.leaf_count = leaf_count
        self.width = width
        bins = defaultdict(list)
        for tree_id, entry in sorted(snapshot.items()):
            bins[(tree_id - 1) // width].append(entry)
        self.bins = {index: tuple(entries) for index, entries in bins.items()}
        level = {index: leaf_hash(entries) for index, entries in self.bins.items()}
        self.levels = [level]
        child_count = leaf_count
        while child_count > 1:
            parents = {index // 2 for index in level}
            level = {
                index: bundle(level.get(index * 2, EMPTY), level.get(index * 2 + 1, EMPTY))
                for index in parents
            }
            self.levels.append(level)
            child_count //= 2


@dataclass
class Comparison:
    checked: int
    spared_leaves: int
    windows: list


def compare(reference, replica):
    result = Comparison(checked=0, spared_leaves=0, windows=[])

    def visit(depth, index):
        first = reference.levels[depth].get(index, EMPTY)
        second = replica.levels[depth].get(index, EMPTY)
        result.checked += 1
        if first == second:
            result.spared_leaves += 1 << depth
        elif depth == 0:
            result.windows.append((index, first.hex(), second.hex()))
        else:
            visit(depth - 1, index * 2)
            visit(depth - 1, index * 2 + 1)

    visit(len(reference.levels) - 1, 0)
    return result
