"""跨语言依赖图模型。"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DependencyNode:
    """表示统一依赖图中的文件或模块节点。"""

    id: str
    label: str
    path: str
    language: str
    kind: str = "module"


@dataclass(frozen=True)
class DependencyEdge:
    """表示统一依赖图中的有向依赖边。"""

    source: str
    target: str
    kind: str


@dataclass
class DependencyGraph:
    """保存跨语言依赖节点、边和结构分析结果。"""

    nodes: dict[str, DependencyNode] = field(default_factory=dict[str, DependencyNode])
    directory_nodes: dict[str, DependencyNode] = field(default_factory=dict[str, DependencyNode])
    edges: list[DependencyEdge] = field(default_factory=list[DependencyEdge])
    incoming_counts: Counter[str] = field(default_factory=Counter[str])
    outgoing_counts: Counter[str] = field(default_factory=Counter[str])
    cycles: list[list[str]] = field(default_factory=list[list[str]])
    isolated_nodes: list[str] = field(default_factory=list[str])
    directory_edges: Counter[tuple[str, str]] = field(default_factory=Counter[tuple[str, str]])
    entry_nodes: list[str] = field(default_factory=list[str])

    def dependencies_of(self, node_id: str) -> list[str]:
        """返回指定节点直接依赖的节点列表。"""
        return sorted(edge.target for edge in self.edges if edge.source == node_id)

    def dependents_of(self, node_id: str) -> list[str]:
        """返回直接依赖指定节点的节点列表。"""
        return sorted(edge.source for edge in self.edges if edge.target == node_id)

    def shortest_paths_from_entries(self) -> tuple[dict[str, int], dict[str, str]]:
        """计算所有入口到可达节点的最短距离和父节点。"""
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            outgoing[edge.source].append(edge.target)
        distances = {node_id: 0 for node_id in self.entry_nodes if node_id in self.nodes}
        parents: dict[str, str] = {}
        queue = deque(distances)
        while queue:
            source = queue.popleft()
            for target in outgoing[source]:
                if target in distances:
                    continue
                distances[target] = distances[source] + 1
                parents[target] = source
                queue.append(target)
        return distances, parents
