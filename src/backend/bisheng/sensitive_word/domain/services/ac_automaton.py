from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class _Node:
    children: Dict[str, '_Node'] = field(default_factory=dict)
    fail: '_Node | None' = None
    outputs: List[str] = field(default_factory=list)


class ACAutomaton:
    def __init__(self, words: Iterable[str]) -> None:
        self.root = _Node()
        self.root.fail = self.root
        for word in words:
            self._insert(word)
        self._build_fail_links()

    def _insert(self, word: str) -> None:
        node = self.root
        for char in word:
            node = node.children.setdefault(char, _Node())
        if word not in node.outputs:
            node.outputs.append(word)

    def _build_fail_links(self) -> None:
        queue = deque()
        for child in self.root.children.values():
            child.fail = self.root
            queue.append(child)

        while queue:
            current = queue.popleft()
            for char, child in current.children.items():
                fail_node = current.fail
                while fail_node is not self.root and char not in fail_node.children:
                    fail_node = fail_node.fail
                child.fail = fail_node.children.get(char, self.root) if fail_node else self.root
                child.outputs.extend(child.fail.outputs if child.fail else [])
                queue.append(child)

    def find_all(self, text: str) -> Counter[str]:
        counter: Counter[str] = Counter()
        node = self.root
        for char in text:
            while node is not self.root and char not in node.children:
                node = node.fail or self.root
            node = node.children.get(char, self.root)
            for word in node.outputs:
                counter[word] += 1
        return counter
