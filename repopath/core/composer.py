"""Analyzer 结果合成器。"""

from datetime import datetime

from ..model.report import RepositoryReport
from ..model.result import AnalysisState
from .context import AnalysisContext


def compose_report(
    context: AnalysisContext, state: AnalysisState
) -> RepositoryReport:
    """将各 Analyzer 结果合成为统一的 RepositoryReport。"""
    return RepositoryReport(
        repository=context.repository,
        source=context.source,
        generated_at=datetime.now()
        .astimezone()
        .isoformat(timespec="seconds"),
        options=context.options,
        files=state.artifacts.files,
        stats=state.artifacts.stats,
        python=state.artifacts.python,
        cpp=state.artifacts.cpp,
        git=state.artifacts.git,
        dependencies=state.artifacts.dependencies,
        insights=state.artifacts.insights,
        reading_guide=state.artifacts.reading_guide,
        analyzer_durations=state.durations,
        warnings=state.warnings,
        errors=state.errors,
        analyzer_results=state.results,
    )
