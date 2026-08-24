"""Provider 通用协议。"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol


class RepositoryFileProvider(Protocol):
    """定义 Analyzer 使用的仓库文件读取协议。"""

    def iter_files(self, excluded_paths: set[Path] | None = None) -> Iterator[Path]:
        """遍历当前仓库中可分析的文件。"""
        ...

    def read_text(self, path: Path) -> str | None:
        """读取文本文件并在不可读取时返回空值。"""
        ...
