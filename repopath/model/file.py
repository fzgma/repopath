"""文件分析结果模型。"""

from dataclasses import dataclass
from pathlib import Path

from .language import Language

FILE_STATISTICS_SCOPE = "文件数、行数、语言和目录统计仅包含成功读取的文本文件。"


@dataclass(frozen=True)
class FileRecord:
    """记录成功读取的文本文件路径、语言和代码规模。"""

    path: Path
    language: Language
    lines: int
    non_empty_lines: int
    comment_lines: int = 0
