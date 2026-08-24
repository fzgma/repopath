"""文件和代码统计分析器。"""

from ..core.context import AnalysisContext
from ..model.result import AnalysisResult, AnalysisState, AnalyzerName
from ..model.language import language_family
from ..model.statistics import RepositoryStats
from .base import Analyzer


class StatisticsAnalyzer(Analyzer):
    """根据文件扫描结果统计语言、代码行数和主要目录。"""

    name = AnalyzerName.STATISTICS

    def analyze(self, context: AnalysisContext, state: AnalysisState) -> AnalysisResult:
        """汇总文件数量、非空行数、语言和目录分布。"""
        files = state.artifacts.files
        stats = RepositoryStats()
        for file in files:
            language = str(file.language)
            stats.language_counts[language] += 1
            stats.language_lines[language] += file.non_empty_lines
            stats.language_comment_lines[language] += file.comment_lines
            family = language_family(file.language)
            stats.language_family_counts[family] += 1
            stats.language_family_lines[family] += file.non_empty_lines
            relative = file.path.relative_to(context.repository.root)
            directory = relative.parts[0] if len(relative.parts) > 1 else "."
            stats.directory_counts[directory] += 1
            stats.directory_lines[directory] += file.non_empty_lines
        state.artifacts.stats = stats
        return AnalysisResult(name=self.name)
