"""本地文件系统 Provider。"""

import os
from collections.abc import Iterator
from pathlib import Path

from ..model.repository import Repository


IGNORED_DIRS = {
    ".agents",
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

IGNORED_FILES = {"REPOPATH_REPORT.md", "REPOPATH_REPORT.json"}


class FileSystemProvider:
    """提供仓库内文件遍历和文本读取能力。"""

    def __init__(
        self,
        repository: Repository,
        ignored_dirs: set[str] | None = None,
        ignored_files: set[str] | None = None,
    ) -> None:
        """创建绑定到指定仓库的文件系统 Provider。"""
        self.repository = repository
        self.ignored_dirs = ignored_dirs or IGNORED_DIRS
        self.ignored_files = ignored_files or IGNORED_FILES

    def is_ignored(self, path: Path) -> bool:
        """判断文件是否位于需要跳过的目录中。"""
        relative = path.resolve().relative_to(self.repository.root)
        return any(part in self.ignored_dirs for part in relative.parts)

    def iter_files(self, excluded_paths: set[Path] | None = None) -> Iterator[Path]:
        """剪枝遍历仓库文件并跳过缓存、构建目录和排除路径。"""
        excluded = {path.resolve() for path in (excluded_paths or set())}
        for directory, subdirectories, file_names in os.walk(self.repository.root):
            subdirectories[:] = sorted(
                name for name in subdirectories if name not in self.ignored_dirs
            )
            for name in sorted(file_names):
                path = Path(directory, name)
                if path.name not in self.ignored_files and path.resolve() not in excluded:
                    yield path

    def read_text(self, path: Path) -> str | None:
        """以 UTF-8 容错模式读取文件内容。"""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
