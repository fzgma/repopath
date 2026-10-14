"""基于可核查证据生成有限阅读指南，不使用热度或规模推断阅读价值。"""

from ..core.context import AnalysisContext
from ..model.result import AnalysisResult, AnalysisState, AnalyzerName
from .base import Analyzer
from .reading_cpp import collect_cpp
from .reading_documents import collect_documents, collect_manifests
from .reading_python import collect_python
from .reading_support import ReadingCollector


class ReadingAnalyzer(Analyzer):
    """独立于依赖图组合文档、清单与已启用语言的静态证据。"""

    name = AnalyzerName.READING

    def analyze(
        self, context: AnalysisContext, state: AnalysisState
    ) -> AnalysisResult:
        """只分析已扫描文件，不构建、不执行仓库、不访问网络。"""
        collector = ReadingCollector(context, state)
        collector.guide.capabilities.extend(
            [
                "通用：Markdown 章节、本地链接及 pyproject.toml、package.json 的入口声明。",
                "按类别、主题和文件交错展示；顺序不表示重要性或运行顺序。",
                "其他语言：仅文档、清单和链接导航。",
            ]
        )
        collect_documents(collector)
        collect_manifests(collector)
        collect_python(collector, state)
        collect_cpp(collector, state)
        state.artifacts.reading_guide = collector.select(
            context.options.reading_limit
        )
        return AnalysisResult(name=self.name)
