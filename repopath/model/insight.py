"""核心评分、阅读顺序和风险热点模型。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleScore:
    """保存模块总分及其可解释评分组成。"""

    node_id: str
    label: str
    path: str
    language: str
    lines: int
    incoming: int
    outgoing: int
    entry_distance: int | None
    git_changes: int
    recent_changes: int
    size_score: float
    dependency_score: float
    entry_score: float
    git_score: float
    total_score: float


@dataclass(frozen=True)
class ReadingRecommendation:
    """表示一个带推荐原因的代码阅读项。"""

    rank: int
    node_id: str
    path: str
    language: str
    score: float
    entry_distance: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReadingPath:
    """表示入口到推荐模块的一条最短依赖路径。"""

    entry: str
    target: str
    nodes: tuple[str, ...]


@dataclass(frozen=True)
class RiskHotspot:
    """表示依赖重要性与修改热度共同较高的文件。"""

    node_id: str
    path: str
    language: str
    dependency_score: float
    git_changes: int
    risk_score: float


@dataclass
class RepositoryInsights:
    """保存统一核心评分、阅读顺序和风险热点。"""

    module_scores: list[ModuleScore] = field(default_factory=list[ModuleScore])
    reading_order: list[ReadingRecommendation] = field(default_factory=list[ReadingRecommendation])
    reading_paths: list[ReadingPath] = field(default_factory=list[ReadingPath])
    hotspots: list[RiskHotspot] = field(default_factory=list[RiskHotspot])
