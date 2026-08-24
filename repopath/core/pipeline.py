"""Analyzer Pipeline。"""

from collections.abc import Iterable
from collections.abc import Callable
from time import perf_counter

from ..analyzer.base import Analyzer
from ..analyzer.cpp import CppAnalyzer
from ..analyzer.file_analyzer import FileAnalyzer
from ..analyzer.git_analyzer import GitAnalyzer
from ..analyzer.python import PythonAnalyzer
from ..analyzer.statistics_analyzer import StatisticsAnalyzer
from ..analyzer.dependency_analyzer import DependencyAnalyzer
from ..analyzer.insight_analyzer import InsightAnalyzer
from ..model.options import AnalysisOptions
from ..model.result import (
    AnalysisProgress,
    AnalysisResult,
    AnalysisState,
    AnalysisStatus,
)
from .context import AnalysisContext


class Pipeline:
    """按固定顺序执行多个 Analyzer 并保存中间结果。"""

    def __init__(self, analyzers: Iterable[Analyzer]) -> None:
        """创建包含指定 Analyzer 的 Pipeline。"""
        self.analyzers = list(analyzers)

    def run(
        self,
        context: AnalysisContext,
        progress_callback: Callable[[AnalysisProgress], None]
        | None = None,
    ) -> AnalysisState:
        """执行所有 Analyzer 并将单个失败转换为结果错误。"""
        state = AnalysisState()
        analyzers = [
            analyzer
            for analyzer in self.analyzers
            if context.options.analyzer_enabled(analyzer.name)
        ]
        total = len(analyzers)
        for index, analyzer in enumerate(analyzers, start=1):
            if progress_callback:
                progress_callback(
                    AnalysisProgress(
                        analyzer.name,
                        index,
                        total,
                        int((index - 1) / total * 100),
                        AnalysisStatus.RUNNING,
                    )
                )
            started_at = perf_counter()
            try:
                result = analyzer.analyze(context, state)
            except Exception as exc:
                result = AnalysisResult(
                    name=analyzer.name,
                    errors=[f"{analyzer.name} 分析失败：{exc}"],
                )
            result.duration_seconds = round(
                perf_counter() - started_at, 6
            )
            state.add(result)
            if progress_callback:
                progress_callback(
                    AnalysisProgress(
                        analyzer.name,
                        index,
                        total,
                        int(index / total * 100),
                        AnalysisStatus.FINISHED,
                    )
                )
        return state


def default_pipeline(
    options: AnalysisOptions | None = None,
) -> Pipeline:
    """创建 RepoPath 默认分析流程。"""
    return Pipeline(
        [
            FileAnalyzer(),
            StatisticsAnalyzer(),
            PythonAnalyzer(),
            CppAnalyzer(),
            GitAnalyzer(),
            DependencyAnalyzer(),
            InsightAnalyzer(),
        ]
    )
