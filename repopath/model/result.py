"""Analyzer 通用结果和 Pipeline 状态模型。"""

from dataclasses import dataclass, field
from enum import StrEnum

from .cpp import CppAnalysis
from .dependency import DependencyGraph
from .file import FileRecord
from .git import GitSummary
from .insight import RepositoryInsights
from .python import PythonAnalysis
from .statistics import RepositoryStats


class AnalyzerName(StrEnum):
    """定义默认 Pipeline 中稳定的分析器标识。"""

    FILES = "files"
    STATISTICS = "statistics"
    PYTHON = "python"
    CPP = "cpp"
    GIT = "git"
    DEPENDENCIES = "dependencies"
    INSIGHTS = "insights"


class AnalysisStatus(StrEnum):
    """定义 Pipeline 阶段进度使用的执行状态。"""

    RUNNING = "running"
    FINISHED = "finished"


@dataclass
class AnalysisArtifacts:
    """保存各 Analyzer 产出的具名领域数据。"""

    files: list[FileRecord] = field(default_factory=list[FileRecord])
    stats: RepositoryStats = field(default_factory=RepositoryStats)
    python: PythonAnalysis = field(default_factory=PythonAnalysis)
    cpp: CppAnalysis = field(default_factory=CppAnalysis)
    git: GitSummary = field(default_factory=GitSummary)
    dependencies: DependencyGraph = field(default_factory=DependencyGraph)
    insights: RepositoryInsights = field(default_factory=RepositoryInsights)


@dataclass
class AnalysisResult:
    """记录一个 Analyzer 的执行状态、告警和错误。"""

    name: AnalyzerName
    warnings: list[str] = field(default_factory=list[str])
    errors: list[str] = field(default_factory=list[str])
    duration_seconds: float = 0.0

    @property
    def successful(self) -> bool:
        """判断 Analyzer 是否没有产生错误。"""
        return not self.errors


@dataclass
class AnalysisState:
    """保存 Pipeline 中各 Analyzer 的执行结果。"""

    artifacts: AnalysisArtifacts = field(default_factory=AnalysisArtifacts)
    results: dict[AnalyzerName, AnalysisResult] = field(default_factory=dict[AnalyzerName, AnalysisResult])

    def add(self, result: AnalysisResult) -> None:
        """保存一个 Analyzer 结果并按名称索引。"""
        self.results[result.name] = result

    @property
    def warnings(self) -> list[str]:
        """汇总所有 Analyzer 的警告信息。"""
        return [warning for result in self.results.values() for warning in result.warnings]

    @property
    def errors(self) -> list[str]:
        """汇总所有 Analyzer 的错误信息。"""
        return [error for result in self.results.values() for error in result.errors]

    @property
    def durations(self) -> dict[str, float]:
        """返回各 Analyzer 的执行耗时。"""
        return {name: result.duration_seconds for name, result in self.results.items()}


@dataclass(frozen=True)
class AnalysisProgress:
    """描述 Pipeline 的阶段级进度事件。"""

    analyzer: AnalyzerName
    index: int
    total: int
    percent: int
    status: AnalysisStatus
