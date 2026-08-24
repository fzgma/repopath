"""跨语言统一依赖图分析器。"""

from collections import defaultdict

from ..model.dependency import DependencyEdge, DependencyGraph, DependencyNode
from ..core.context import AnalysisContext
from ..model.result import AnalysisResult, AnalysisState, AnalyzerName
from .base import Analyzer


class DependencyAnalyzer(Analyzer):
    """合并 Python import 和 C++ include 并分析图结构。"""

    name = AnalyzerName.DEPENDENCIES

    def analyze(self, context: AnalysisContext, state: AnalysisState) -> AnalysisResult:
        """生成跨语言依赖节点、边、循环和目录聚合结果。"""
        python = state.artifacts.python
        cpp = state.artifacts.cpp
        graph = DependencyGraph()
        python_ids: dict[str, str] = {}
        cpp_ids: dict[str, str] = {}

        for module, path in sorted(python.module_paths.items()):
            relative = context.repository.relative_path(path)
            node_id = f"python:{module}"
            python_ids[module] = node_id
            graph.nodes[node_id] = DependencyNode(node_id, module, relative, "Python")

        for path in sorted(cpp.files, key=lambda item: str(item)):
            relative = context.repository.relative_path(path)
            node_id = f"cpp:{relative}"
            cpp_ids[relative] = node_id
            graph.nodes[node_id] = DependencyNode(node_id, relative, relative, "C++", "file")

        edge_keys: set[tuple[str, str, str]] = set()
        for edge in python.dependencies:
            source = python_ids.get(edge.source)
            target = python_ids.get(edge.target)
            if source and target:
                edge_keys.add((source, target, edge.kind))
        for edge in cpp.dependencies:
            source = cpp_ids.get(edge.source)
            target = cpp_ids.get(edge.target)
            if source and target:
                edge_keys.add((source, target, edge.kind))

        graph.edges = [DependencyEdge(*edge) for edge in sorted(edge_keys)]
        for edge in graph.edges:
            graph.outgoing_counts[edge.source] += 1
            graph.incoming_counts[edge.target] += 1
            source_dir = _directory(graph.nodes[edge.source].path)
            target_dir = _directory(graph.nodes[edge.target].path)
            graph.directory_edges[(source_dir, target_dir)] += 1

        for directory in sorted(
            {_directory(node.path) for node in graph.nodes.values()}
        ):
            node_id = f"directory:{directory}"
            graph.directory_nodes[node_id] = DependencyNode(
                node_id,
                directory,
                directory,
                "Mixed",
                "directory",
            )

        graph.entry_nodes = sorted(
            {
                python_ids[module]
                for module, path in python.module_paths.items()
                if any(entry.path == path for entry in python.entry_points)
            }
            | {
                cpp_ids[context.repository.relative_path(entry.path)]
                for entry in cpp.entry_points
                if context.repository.relative_path(entry.path) in cpp_ids
            }
        )
        graph.cycles = _find_cycles(graph)
        graph.isolated_nodes = sorted(
            node_id
            for node_id in graph.nodes
            if graph.incoming_counts[node_id] == 0 and graph.outgoing_counts[node_id] == 0
        )
        state.artifacts.dependencies = graph
        return AnalysisResult(name=self.name)


def _directory(path: str) -> str:
    """返回报告路径的顶层目录。"""
    return path.split("/", 1)[0] if "/" in path else "."


def _find_cycles(graph: DependencyGraph) -> list[list[str]]:
    """使用强连通分量识别依赖循环。"""
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append(edge.target)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    components: list[list[str]] = []

    def visit(node_id: str) -> None:
        """递归计算单个节点所属的强连通分量。"""
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        active.add(node_id)
        for target in outgoing[node_id]:
            if target not in indices:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in active:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] != indices[node_id]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            active.remove(member)
            component.append(member)
            if member == node_id:
                break
        self_loop = len(component) == 1 and component[0] in outgoing[component[0]]
        if len(component) > 1 or self_loop:
            components.append(sorted(component))

    for node_id in sorted(graph.nodes):
        if node_id not in indices:
            visit(node_id)
    return sorted(components, key=lambda item: (item[0], len(item)))
