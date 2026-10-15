"""Provider 通用协议。"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from ..model.git import GitSummary


class RepositoryFileProvider(Protocol):
    """定义 Analyzer 使用的仓库文件读取协议。"""

    def iter_files(
        self, excluded_paths: set[Path] | None = None
    ) -> Iterator[Path]:
        """遍历当前仓库中可分析的文件。"""
        ...

    def read_text(self, path: Path) -> str | None:
        """读取可分析文本；非文本、编码不支持、超限或不可读时返回空值。"""
        ...


class RepositoryGitProvider(Protocol):
    """定义 Analyzer 使用的 Git 摘要读取协议。"""

    def summary(self, period: str = "all") -> GitSummary:
        """读取指定历史范围内的 Git 摘要。"""
        ...
