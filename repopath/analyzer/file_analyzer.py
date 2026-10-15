"""文件扫描分析器。"""

from ..core.context import AnalysisContext
from ..model.file import FileRecord
from ..model.language import detect_language
from ..model.result import AnalysisResult, AnalysisState, AnalyzerName
from .base import Analyzer


class FileAnalyzer(Analyzer):
    """扫描可读取的文本文件并记录语言和代码规模。"""

    name = AnalyzerName.FILES

    def analyze(
        self, context: AnalysisContext, state: AnalysisState
    ) -> AnalysisResult:
        """扫描仓库文件并生成文件记录列表。"""
        records: list[FileRecord] = []
        warnings: list[str] = []
        skipped = 0
        for path in context.filesystem.iter_files(
            context.excluded_paths
        ):
            context.cancellation.raise_if_cancelled()
            source = context.filesystem.read_text(path)
            if source is None:
                skipped += 1
                continue
            lines = source.splitlines()
            comment_lines = sum(
                line.strip().startswith(("#", "//", "/*", "*", "*/"))
                for line in lines
            )
            records.append(
                FileRecord(
                    path=path,
                    language=detect_language(path),
                    lines=len(lines),
                    non_empty_lines=sum(
                        bool(line.strip()) for line in lines
                    ),
                    comment_lines=comment_lines,
                )
            )
        if skipped:
            warnings.append(
                f"已跳过 {skipped} 个非文本、编码不支持、超出大小限制或无法读取的文件；"
                "这些文件不计入文件数、行数、语言和目录统计。"
            )
        state.artifacts.files = records
        return AnalysisResult(name=self.name, warnings=warnings)
