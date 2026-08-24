"""Analyzer 结果合成器。"""

from ..model.git import GitSummary
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
        files=state.get_data("files", []),
        stats=state.get_data("statistics", RepositoryStats()),
        python=state.get_data("python", PythonAnalysis()),
        cpp=state.get_data("cpp", CppAnalysis()),
        git=state.get_data("git", GitSummary()),
        warnings=state.warnings,
        errors=state.errors,
    )
