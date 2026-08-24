"""文件扫描分析器。"""

from ..model.file import FileRecord
from ..model.result import AnalysisResult, AnalysisState
from ..model.language import detect_language
from .base import Analyzer


class FileAnalyzer(Analyzer):
    """扫描文件并记录语言和代码规模。"""

    name = "files"

    def analyze(self, context, state: AnalysisState) -> AnalysisResult:
        """扫描仓库文件并生成文件记录列表。"""
        records = []
        warnings = []
        for path in context.filesystem.iter_files(context.excluded_paths):
            source = context.filesystem.read_text(path)
            if source is None:
                warnings.append(f"无法读取文件：{context.repository.relative_path(path)}")
                continue
            lines = source.splitlines()
            records.append(
                FileRecord(
                    path=path,
                    language=detect_language(path),
                    lines=len(lines),
                    non_empty_lines=sum(bool(line.strip()) for line in lines),
                )
            )
        return AnalysisResult(name=self.name, data=records, warnings=warnings)
