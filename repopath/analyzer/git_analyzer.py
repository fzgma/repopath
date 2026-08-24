"""Git 历史分析器。"""

from ..core.context import AnalysisContext
from ..model.result import AnalysisResult, AnalysisState, AnalyzerName
from .base import Analyzer


class GitAnalyzer(Analyzer):
    """分析提交数、贡献者、最近提交和高频修改路径。"""

    name = AnalyzerName.GIT

    def analyze(
        self, context: AnalysisContext, state: AnalysisState
    ) -> AnalysisResult:
        """读取 Git Provider 并返回 Git 历史摘要。"""
        summary = context.git.summary(context.options.git_period)
        warnings = [summary.error] if summary.error else []
        if summary.shallow:
            warnings.append("当前仓库是浅克隆，Git 演进统计可能不完整")
        state.artifacts.git = summary
        return AnalysisResult(name=self.name, warnings=warnings)
