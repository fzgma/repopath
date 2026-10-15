"""本地文件系统 Provider。"""

import codecs
import os
import re
from collections.abc import Iterator
from fnmatch import fnmatch
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

_BINARY_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"SQLite format 3\x00",
    b"%PDF-",
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",
    b"\x7fELF",
)
_CONTROL_CHARACTERS = re.compile(r"[\x01-\x08\x0e-\x1f\x7f]")


def _decode_text(content: bytes) -> str | None:
    """按内容排除二进制，严格解码支持的文本编码并统一换行。"""
    if content.startswith(_BINARY_SIGNATURES) or (
        content.startswith(b"RIFF")
        and content[8:12] in {b"WEBP", b"WAVE", b"AVI "}
    ):
        return None
    # UTF-32 LE 与 UTF-16 LE 共用前两个 BOM 字节，必须先检查 UTF-32。
    if content.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    try:
        text = content.decode(encoding)
    except UnicodeError:
        return None
    # 解码后再检查，避免将 UTF-16/32 的正常零字节误当成二进制。
    if "\x00" in text:
        return None
    # 允许常见文本空白及少量终端控制字符，控制字符密集的内容不计行。
    if len(_CONTROL_CHARACTERS.findall(text)) > len(text) * 0.1:
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


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
        """读取支持编码的文本，跳过二进制、超限及不可读文件。"""
        try:
            if (
                self.max_file_size is not None
                and path.stat().st_size > self.max_file_size
            ):
                return None
            with path.open("rb") as stream:
                content = stream.read(
                    -1 if self.max_file_size is None else self.max_file_size + 1
                )
            if self.max_file_size is not None and len(content) > self.max_file_size:
                return None
            return _decode_text(content)
        except OSError:
            return None
