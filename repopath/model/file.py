"""文件分析结果模型。"""

from dataclasses import dataclass
from pathlib import Path

from .language import Language


@dataclass(frozen=True)
class FileRecord:
    """记录单个文件的路径、语言和代码规模。"""

    path: Path
    language: Language
    lines: int
    non_empty_lines: int
