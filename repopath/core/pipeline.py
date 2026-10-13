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
    AnalyzerName,
    AnalyzerStatus,
)
from .context import AnalysisContext
from .control import AnalysisCancelled


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
        prerequisites = {
            AnalyzerName.STATISTICS: [AnalyzerName.FILES],
            AnalyzerName.PYTHON: [AnalyzerName.FILES],
            AnalyzerName.CPP: [AnalyzerName.FILES],
            AnalyzerName.DEPENDENCIES: [
                name for name in (AnalyzerName.PYTHON, AnalyzerName.CPP)
                if context.options.analyzer_enabled(name)
            ],
            AnalyzerName.INSIGHTS: [AnalyzerName.DEPENDENCIES],
        }
        for analyzer in self.analyzers:
            if not context.options.analyzer_enabled(analyzer.name):
                state.add(AnalysisResult(
                    name=analyzer.name,
                    status=AnalyzerStatus.NOT_RUN,
                    reason=f"当前配置未启用 {analyzer.name}（profile={context.options.profile}）",
                ))
        analyzers = [
            analyzer
            for analyzer in self.analyzers
            if context.options.analyzer_enabled(analyzer.name)
        ]
        total = len(analyzers)
        for index, analyzer in enumerate(analyzers, start=1):
            context.cancellation.raise_if_cancelled()
            unavailable = [
                name for name in prerequisites.get(analyzer.name, [])
                if name not in state.results or not state.results[name].successful
            ]
            if unavailable:
                state.add(AnalysisResult(
                    name=analyzer.name,
                    status=AnalyzerStatus.NOT_RUN,
                    reason="上游分析未完成：" + ", ".join(unavailable),
                ))
                if progress_callback:
                    progress_callback(AnalysisProgress(
                        analyzer.name, index, total,
                        int(index / total * 100), AnalysisStatus.FINISHED,
                    ))
                continue
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
            except AnalysisCancelled:
                raise
            except Exception as exc:
                result = AnalysisResult(
                    name=analyzer.name,
                    errors=[f"{analyzer.name} 分析失败：{exc}"],
                )
            result.duration_seconds = round(
                perf_counter() - started_at, 6
            )
            if result.errors:
                result.status = AnalyzerStatus.FAILED
                result.reason = "；".join(result.errors)
            state.add(result)
            context.cancellation.raise_if_cancelled()
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
