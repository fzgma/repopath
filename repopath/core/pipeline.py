"""Analyzer Pipeline。"""

from collections.abc import Iterable

from ..analyzer.base import Analyzer
from ..analyzer.file_analyzer import FileAnalyzer
from ..analyzer.git_analyzer import GitAnalyzer
from ..analyzer.python_analyzer import PythonAnalyzer
from ..analyzer.statistics_analyzer import StatisticsAnalyzer
from ..model.result import AnalysisResult, AnalysisState
from .context import AnalysisContext


class Pipeline:
    """按固定顺序执行多个 Analyzer 并保存中间结果。"""

    def __init__(self, analyzers: Iterable[Analyzer]) -> None:
        """创建包含指定 Analyzer 的 Pipeline。"""
        self.analyzers = list(analyzers)

    def run(self, context: AnalysisContext) -> AnalysisState:
        """执行所有 Analyzer 并将单个失败转换为结果错误。"""
        state = AnalysisState()
        for analyzer in self.analyzers:
            try:
                result = analyzer.analyze(context, state)
            except Exception as exc:
                result = AnalysisResult(name=analyzer.name, errors=[f"{analyzer.name} 分析失败：{exc}"])
            state.add(result)
        return state


def default_pipeline() -> Pipeline:
    """创建 RepoPath 默认分析流程。"""
    return Pipeline([FileAnalyzer(), StatisticsAnalyzer(), PythonAnalyzer(), GitAnalyzer()])
