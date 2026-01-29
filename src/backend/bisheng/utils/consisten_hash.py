import bisect
import hashlib
from typing import Dict, List, Optional, Any


class ConsistentHash:

    def __init__(self, nodes: Optional[List[str]] = None,
                 virtual_replicas: int = 100,
                 hash_fn: Optional[Any] = None):
        self.virtual_replicas = virtual_replicas
        self.hash_fn = hash_fn or (lambda x: int(hashlib.md5(x.encode()).hexdigest(), 16))

        # save hash ring: hash_value -> node
        self.ring: Dict[int, str] = {}
        # save sorted hash values for find
        self.sorted_hashes: List[int] = []

        # save all nodes
        self.nodes = set()

        # init nodes
        if nodes:
            for node in nodes:
                self.add_node(node)

    def add_node(self, node: str) -> None:
        if node in self.nodes:
            return

        self.nodes.add(node)

        # create virtual nodes
        for i in range(self.virtual_replicas):
            # virtual node name: node#0, node#1, ...
            virtual_node = f"{node}#{i}"

            # calc
            hash_value = self.hash_fn(virtual_node)

            # Avoid hash collisions
            while hash_value in self.ring:
                virtual_node = f"{virtual_node}#"
                hash_value = self.hash_fn(virtual_node)

            # 添加到环中
            self.ring[hash_value] = node

        # resort hash values
        self._update_sorted_hashes()

    def remove_node(self, node: str) -> None:
        if node not in self.nodes:
            return

        self.nodes.remove(node)

        # Remove all virtual nodes of this node.
        hashes_to_remove = [
            hash_val for hash_val, n in self.ring.items()
            if n == node
        ]

        for hash_val in hashes_to_remove:
            del self.ring[hash_val]

        self._update_sorted_hashes()

    def _update_sorted_hashes(self) -> None:
        """Update the sorted hash value list"""
        self.sorted_hashes = sorted(self.ring.keys())

    def find_node(self, key: str) -> Optional[str]:
        """
        Retrieve the corresponding node based on the key

        Args:
            key: hash key

        Returns:
            node name or None if no nodes exist
        """
        if not self.ring:
            return None

        key_hash = self.hash_fn(key)

        # Use binary search to find the first node that is greater than or equal to key_hash.
        idx = bisect.bisect_left(self.sorted_hashes, key_hash)

        # If idx is out of range, return to the beginning of the ring.
        if idx == len(self.sorted_hashes):
            idx = 0

        # return node name
        return self.ring[self.sorted_hashes[idx]]

    def find_nodes(self, key: str, count: int = 1) -> List[str]:
        """
        Retrieves multiple nodes for a given key (in clockwise order).

        Args:
            key: hash key
            count: Number of nodes to be returned

        Returns:
            Returns a list of nodes that processed the key.
        """
        if not self.ring or count <= 0:
            return []

        if count > len(self.nodes):
            count = len(self.nodes)

        key_hash = self.hash_fn(key)

        idx = bisect.bisect_left(self.sorted_hashes, key_hash)

        if idx == len(self.sorted_hashes):
            idx = 0

        nodes = []
        seen_nodes = set()

        while len(nodes) < count:
            node = self.ring[self.sorted_hashes[idx]]

            if node not in seen_nodes:
                seen_nodes.add(node)
                nodes.append(node)

            idx += 1
            if idx == len(self.sorted_hashes):
                idx = 0

        return nodes

    def get_ring_size(self) -> int:
        return len(self.ring)

    def get_node_count(self) -> int:
        return len(self.nodes)

    def get_all_nodes(self) -> List[str]:
        return list(self.nodes)


if __name__ == "__main__":
    # 创建一致性哈希环
    ch = ConsistentHash(virtual_replicas=10)

    # 测试数据分布
    test_keys = ["key1", "key2", "key3", "key4", "key5", "key6", "key7", "key8", "key9", "key10"]

    print("初始节点分布:")
    distribution = {}
    for key in test_keys:
        node = ch.find_node(key)
        distribution[node] = distribution.get(node, 0) + 1
        print(f"  {key} -> {node}")

    print("\n数据分布统计:")
    for node, count in distribution.items():
        print(f"  {node}: {count} 个键")

    # 添加新节点
    print("\n添加新节点 server4")
    ch.add_node("server4")

    # 查看添加节点后的数据分布变化
    moved_keys = []
    for key in test_keys:
        new_node = ch.find_node(key)
        # 这里简化比较，实际应该记录之前分配的节点
        print(f"  {key} -> {new_node}")

    # 获取多个节点
    print("\n获取处理 'key1' 的3个节点:")
    nodes = ch.find_nodes("key1", 3)
    for i, node in enumerate(nodes, 1):
        print(f"  第{i}候选: {node}")

    # 移除节点
    print("\n移除节点 server2")
    ch.remove_node("server2")

    print(f"当前物理节点数: {ch.get_node_count()}")
    print(f"当前虚拟节点数: {ch.get_ring_size()}")
