"""Analyzer 结果合成器。"""

from datetime import datetime

from ..model.git import GitSummary
from ..model.dependency import DependencyGraph
from ..model.insight import RepositoryInsights
from ..model.cpp import CppAnalysis
from ..model.python import PythonAnalysis
from ..model.report import RepositoryReport
from ..model.result import AnalysisState
from ..model.statistics import RepositoryStats
from .context import AnalysisContext


def compose_report(context: AnalysisContext, state: AnalysisState) -> RepositoryReport:
    """将各 Analyzer 结果合成为统一的 RepositoryReport。"""
    return RepositoryReport(
        repository=context.repository,
        source=context.source,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        options=context.options,
        files=state.get_data("files", []),
        stats=state.get_data("statistics", RepositoryStats()),
        python=state.get_data("python", PythonAnalysis()),
        cpp=state.get_data("cpp", CppAnalysis()),
        git=state.get_data("git", GitSummary()),
        dependencies=state.get_data("dependencies", DependencyGraph()),
        insights=state.get_data("insights", RepositoryInsights()),
        analyzer_durations=state.durations,
        warnings=state.warnings,
        errors=state.errors,
    )
