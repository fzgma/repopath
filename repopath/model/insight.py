"""阅读优先级和变更关注度模型。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleScore:
    """保存模块的两类聚合分数及其可解释组成。"""

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
    reading_priority_score: float
    change_attention_score: float


@dataclass(frozen=True)
class ReadingRecommendation:
    """表示一个带推荐原因的代码阅读项。"""

    rank: int
    node_id: str
    path: str
    language: str
    reading_priority_score: float
    entry_distance: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReadingPath:
    """表示入口到推荐模块的一条最短依赖路径。"""

    entry: str
    target: str
    nodes: tuple[str, ...]


@dataclass(frozen=True)
class ChangeAttention:
    """表示依赖暴露和修改活跃度共同较高的文件。"""

    node_id: str
    path: str
    language: str
    dependency_score: float
    git_changes: int
    recent_changes: int
    git_score: float
    change_attention_score: float


@dataclass
class RepositoryInsights:
    """保存阅读优先级、变更关注度和阅读路径。"""

    module_scores: list[ModuleScore] = field(
        default_factory=list[ModuleScore]
    )
    reading_order: list[ReadingRecommendation] = field(
        default_factory=list[ReadingRecommendation]
    )
    reading_paths: list[ReadingPath] = field(
        default_factory=list[ReadingPath]
    )
    change_attention: list[ChangeAttention] = field(
        default_factory=list[ChangeAttention]
    )
