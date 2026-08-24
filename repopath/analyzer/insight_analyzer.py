"""核心模块评分和推荐阅读顺序分析器。"""

from ..core.context import AnalysisContext
from ..model.insight import (
    ModuleScore,
    ReadingPath,
    ReadingRecommendation,
    RepositoryInsights,
    RiskHotspot,
)
from ..model.result import AnalysisResult, AnalysisState, AnalyzerName
from .base import Analyzer


class InsightAnalyzer(Analyzer):
    """根据依赖图、代码规模和 Git 热度生成阅读洞察。"""

    name = AnalyzerName.INSIGHTS

    def analyze(self, context: AnalysisContext, state: AnalysisState) -> AnalysisResult:
        """计算模块评分、阅读顺序、入口路径和风险热点。"""
        graph = state.artifacts.dependencies
        git = state.artifacts.git
        files = state.artifacts.files
        lines_by_path = {
            context.repository.relative_path(file.path): file.non_empty_lines
            for file in files
        }
        distances, parents = graph.shortest_paths_from_entries()
        insights = RepositoryInsights()

        for node_id, node in graph.nodes.items():
            lines = lines_by_path.get(node.path, 0)
            incoming = graph.incoming_counts[node_id]
            outgoing = graph.outgoing_counts[node_id]
            git_changes = git.changed_paths[node.path]
            recent_changes = git.recent_90_days[node.path]
            size_score = round(min(20.0, lines / 25), 2)
            dependency_score = round(min(35.0, incoming * 7 + outgoing * 2), 2)
            distance = distances.get(node_id)
            entry_score = round(max(0.0, 20.0 - (distance or 0) * 4), 2) if distance is not None else 0.0
            git_score = round(min(25.0, git_changes * 2 + recent_changes * 3), 2)
            total_score = round(size_score + dependency_score + entry_score + git_score, 2)
            insights.module_scores.append(
                ModuleScore(
                    node_id,
                    node.label,
                    node.path,
                    node.language,
                    lines,
                    incoming,
                    outgoing,
                    distance,
                    git_changes,
                    recent_changes,
                    size_score,
                    dependency_score,
                    entry_score,
                    git_score,
                    total_score,
                )
            )

        insights.module_scores.sort(key=lambda item: (-item.total_score, item.path))
        reading_scores = sorted(
            insights.module_scores,
            key=lambda item: (
                item.entry_distance is None,
                item.entry_distance if item.entry_distance is not None else 10**9,
                -item.total_score,
                item.path,
            )
        )
        for rank, score in enumerate(reading_scores, start=1):
            reasons = _recommendation_reasons(score)
            insights.reading_order.append(
                ReadingRecommendation(
                    rank,
                    score.node_id,
                    score.path,
                    score.language,
                    score.total_score,
                    score.entry_distance,
                    reasons,
                )
            )
            path = _reading_path(score.node_id, parents)
            if len(path) > 1:
                insights.reading_paths.append(ReadingPath(path[0], path[-1], tuple(path)))

        for score in insights.module_scores:
            risk_score = round(score.dependency_score + score.git_score, 2)
            if score.git_changes and score.dependency_score:
                insights.hotspots.append(
                    RiskHotspot(
                        score.node_id,
                        score.path,
                        score.language,
                        score.dependency_score,
                        score.git_changes,
                        risk_score,
                    )
                )
        insights.hotspots.sort(key=lambda item: (-item.risk_score, item.path))
        state.artifacts.insights = insights
        return AnalysisResult(name=self.name)


def _recommendation_reasons(score: ModuleScore) -> tuple[str, ...]:
    """根据评分明细生成简短的阅读推荐原因。"""
    reasons: list[str] = []
    if score.entry_distance == 0:
        reasons.append("程序入口")
    elif score.entry_distance is not None:
        reasons.append(f"距入口 {score.entry_distance} 层")
    if score.incoming:
        reasons.append(f"被 {score.incoming} 个模块依赖")
    if score.git_changes:
        reasons.append(f"历史修改 {score.git_changes} 次")
    if score.lines:
        reasons.append(f"{score.lines} 行代码")
    return tuple(reasons or ["独立模块"])


def _reading_path(target: str, parents: dict[str, str]) -> list[str]:
    """根据最短路径父节点还原入口到目标的路径。"""
    path = [target]
    while path[-1] in parents:
        path.append(parents[path[-1]])
    return list(reversed(path))
