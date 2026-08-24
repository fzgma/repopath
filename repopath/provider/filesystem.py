"""本地文件系统 Provider。"""

import os
from fnmatch import fnmatch
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

IGNORED_FILES = {
    ".repopath.toml",
    "REPOPATH_REPORT.md",
    "REPOPATH_REPORT.json",
}


class FileSystemProvider:
    """提供仓库内文件遍历和文本读取能力。"""

    def __init__(
        self,
        repository: Repository,
        *,
        ignored_dirs: set[str] | None = None,
        ignored_files: set[str] | None = None,
        excluded_patterns: tuple[str, ...] = (),
        max_file_size: int | None = None,
        follow_symlinks: bool = False,
    ) -> None:
        """创建绑定到指定仓库的文件系统 Provider。"""
        self.repository = repository
        self.ignored_dirs = ignored_dirs or IGNORED_DIRS
        self.ignored_files = ignored_files or IGNORED_FILES
        self.excluded_patterns = excluded_patterns
        self.max_file_size = max_file_size
        self.follow_symlinks = follow_symlinks

    def is_ignored(self, path: Path) -> bool:
        """判断文件是否位于需要跳过的目录中。"""
        relative = path.absolute().relative_to(self.repository.root)
        relative_text = relative.as_posix()
        return any(
            part in self.ignored_dirs for part in relative.parts
        ) or any(
            fnmatch(relative_text, pattern)
            or fnmatch(path.name, pattern)
            for pattern in self.excluded_patterns
        )

    def iter_files(
        self, excluded_paths: set[Path] | None = None
    ) -> Iterator[Path]:
        """剪枝遍历仓库文件并跳过缓存、构建目录和排除路径。"""
        excluded = {
            path.resolve() for path in (excluded_paths or set())
        }
        for directory, subdirectories, file_names in os.walk(
            self.repository.root,
            followlinks=self.follow_symlinks,
        ):
            subdirectories[:] = sorted(
                name
                for name in subdirectories
                if name not in self.ignored_dirs
                and (
                    self.follow_symlinks
                    or not Path(directory, name).is_symlink()
                )
                and not self.is_ignored(Path(directory, name))
            )
            for name in sorted(file_names):
                path = Path(directory, name)
                if (
                    path.name not in self.ignored_files
                    and path.resolve() not in excluded
                    and not self.is_ignored(path)
                ):
                    yield path

    def read_text(self, path: Path) -> str | None:
        """以 UTF-8 容错模式读取文件内容。"""
        try:
            if (
                self.max_file_size is not None
                and path.stat().st_size > self.max_file_size
            ):
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
