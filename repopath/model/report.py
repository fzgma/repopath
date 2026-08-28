"""最终仓库报告模型。"""

from dataclasses import dataclass, field

from .. import __version__
from .dependency import DependencyGraph
from .file import FileRecord
from .cpp import CppAnalysis
from .git import GitSummary
from .insight import RepositoryInsights
from .options import AnalysisOptions
from .python import PythonAnalysis
from .repository import GitHubRateLimit, Repository, RepositorySource
from .statistics import RepositoryStats


@dataclass
class RepositoryReport:
    """组合所有分析器结果供 Renderer 和界面使用。"""

    repository: Repository
    source: RepositorySource | None = None
    github_rate_limit: GitHubRateLimit | None = None
    schema_version: str = "0.4"
    tool_version: str = __version__
    generated_at: str = ""
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    files: list[FileRecord] = field(default_factory=list[FileRecord])
    stats: RepositoryStats = field(default_factory=RepositoryStats)
    python: PythonAnalysis = field(default_factory=PythonAnalysis)
    cpp: CppAnalysis = field(default_factory=CppAnalysis)
    git: GitSummary = field(default_factory=GitSummary)
    dependencies: DependencyGraph = field(
        default_factory=DependencyGraph
    )
    insights: RepositoryInsights = field(
        default_factory=RepositoryInsights
    )
    analyzer_durations: dict[str, float] = field(
        default_factory=dict[str, float]
    )
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list[str])
    errors: list[str] = field(default_factory=list[str])
