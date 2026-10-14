"""最终仓库报告模型。"""

from dataclasses import dataclass, field

from .. import __version__
from .cpp import CppAnalysis
from .dependency import DependencyGraph
from .file import FileRecord
from .git import GitSummary
from .insight import RepositoryInsights
from .options import AnalysisOptions
from .python import PythonAnalysis
from .reading import ReadingGuide
from .repository import GitHubRateLimit, Repository, RepositorySource
from .result import (
    AnalysisAvailability,
    AnalysisResult,
    AnalyzerName,
    AnalyzerStatus,
)
from .statistics import RepositoryStats


@dataclass
class RepositoryReport:
    """组合所有分析器结果供 Renderer 和界面使用。"""

    repository: Repository
    source: RepositorySource | None = None
    github_rate_limit: GitHubRateLimit | None = None
    schema_version: str = "0.6"
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
    analyzer_results: dict[AnalyzerName, AnalysisResult] = field(default_factory=dict)
    reading_guide: ReadingGuide = field(default_factory=ReadingGuide)

    def analyzer_result(self, name: AnalyzerName) -> AnalysisResult:
        """读取执行证据，缺失记录不代表已完成。"""
        return self.analyzer_results.get(
            name,
            AnalysisResult(name, status=AnalyzerStatus.NOT_RUN, reason="没有执行记录"),
        )

    def change_attention_availability(self) -> AnalysisAvailability:
        """区分静态阅读已完成与依赖 Git 的变更关注是否可用。"""
        insights = self.analyzer_result(AnalyzerName.INSIGHTS)
        if insights.status != AnalyzerStatus.COMPLETED:
            return AnalysisAvailability(insights.status, insights.reason)
        git = self.analyzer_result(AnalyzerName.GIT)
        if not git.successful:
            return AnalysisAvailability(
                AnalyzerStatus.NOT_RUN,
                f"Git 分析未完成（{git.status}）：{git.reason or '没有执行记录'}",
            )
        if not self.git.available:
            return AnalysisAvailability(
                AnalyzerStatus.NOT_RUN,
                "Git 历史不可用：" + (self.git.error or "没有可用的 Git 历史"),
            )
        return AnalysisAvailability(AnalyzerStatus.COMPLETED)
