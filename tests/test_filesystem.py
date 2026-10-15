"""文件读取的文本编码、二进制识别和资源边界测试。"""

import base64
import codecs
import sqlite3
from pathlib import Path

import pytest

from repopath.model.repository import Repository
from repopath.provider.filesystem import FileSystemProvider

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aPZsAAAAASUVORK5CYII="
)
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")


@pytest.mark.parametrize(
    "content",
    [
        PNG,
        GIF,
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00",
        b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
    ],
    ids=["png", "gif", "jpeg-header", "ascii-pdf"],
)
def test_binary_content_is_rejected_without_relying_on_extension(
    tmp_path: Path, content: bytes,
) -> None:
    """图片和文档二进制即使伪装成源码或没有后缀也不返回文本。"""
    provider = FileSystemProvider(Repository.from_path(tmp_path))
    for name in ("data", "pretend.py", "pretend.txt"):
        path = tmp_path / name
        path.write_bytes(content)
        assert provider.read_text(path) is None


def test_real_sqlite_database_is_rejected_even_with_source_extension(
    tmp_path: Path,
) -> None:
    """真实数据库中的文本记录不能令 SQLite 被计作代码行。"""
    path = tmp_path / "storage.py"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE notes (body TEXT)")
        connection.execute("INSERT INTO notes VALUES (?)", ("first\nsecond\n" * 50,))
        connection.commit()
    finally:
        connection.close()

    provider = FileSystemProvider(Repository.from_path(tmp_path))
    assert path.read_bytes().startswith(b"SQLite format 3\x00")
    assert provider.read_text(path) is None


@pytest.mark.parametrize(
    ("encoding", "prefix"),
    [
        ("utf-8", b""),
        ("utf-8", codecs.BOM_UTF8),
        ("utf-16-le", codecs.BOM_UTF16_LE),
        ("utf-16-be", codecs.BOM_UTF16_BE),
        ("utf-32-le", codecs.BOM_UTF32_LE),
        ("utf-32-be", codecs.BOM_UTF32_BE),
    ],
    ids=["utf8", "utf8-bom", "utf16-le", "utf16-be", "utf32-le", "utf32-be"],
)
def test_supported_unicode_text_preserves_content_and_normalizes_newlines(
    tmp_path: Path, encoding: str, prefix: bytes,
) -> None:
    """先处理字节序标记，再判断文本，保留原有统一换行行为。"""
    path = tmp_path / "source"
    source = "第一行\r\nsecond\rthird\n\t四\f五\v六\n"
    path.write_bytes(prefix + source.encode(encoding))
    provider = FileSystemProvider(Repository.from_path(tmp_path))

    assert provider.read_text(path) == "第一行\nsecond\nthird\n\t四\f五\v六\n"


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("empty", ""),
        ("script", "#!/bin/sh\nprintf 'hello\\n'\n"),
        ("settings.db", "enabled=true\n"),
        ("icon.svg", '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>\n'),
        ("notes.png", "This is text despite its filename.\n"),
    ],
    ids=["empty", "extensionless", "database-name", "svg", "image-name"],
)
def test_text_is_preserved_regardless_of_filename(
    tmp_path: Path, name: str, source: str,
) -> None:
    """后缀不决定文件内容类型，空文本和 SVG 仍正常读取。"""
    path = tmp_path / name
    path.write_bytes(source.encode("utf-8"))
    provider = FileSystemProvider(Repository.from_path(tmp_path))

    assert provider.read_text(path) == source


@pytest.mark.parametrize(
    "content",
    [
        b"value = 1\n\x00value = 2\n",
        b"\x01\x02\x03\x04" * 100,
        b"valid prefix\n" + b"\xff\x80",
        "中文文本".encode("gbk"),
        codecs.BOM_UTF16_LE + b"\x00\xd8",
        codecs.BOM_UTF32_LE + b"\x00\x00\x11\x00",
        codecs.BOM_UTF8 + b"text\x00tail",
    ],
    ids=["nul", "controls", "invalid-utf8", "unsupported-encoding", "invalid-utf16", "invalid-utf32", "bom-with-nul"],
)
def test_binary_or_unsupported_content_is_not_replaced_and_counted(
    tmp_path: Path, content: bytes,
) -> None:
    """非文本与不支持的编码均不靠替换字符伪装为可统计文本。"""
    path = tmp_path / "payload"
    path.write_bytes(content)
    provider = FileSystemProvider(Repository.from_path(tmp_path))

    assert provider.read_text(path) is None


@pytest.mark.parametrize("suffix", [b"\x00", b"\xff"])
def test_validation_checks_content_after_the_initial_probe(
    tmp_path: Path, suffix: bytes,
) -> None:
    """前段为纯文本不能掩盖大小限制内后段的二进制或损坏编码。"""
    path = tmp_path / "late-data.txt"
    content = b"plain text\n" * 8192 + suffix
    path.write_bytes(content)
    provider = FileSystemProvider(
        Repository.from_path(tmp_path), max_file_size=len(content),
    )

    assert provider.read_text(path) is None


def test_size_limit_accepts_boundary_and_does_not_open_larger_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文件恰好达到上限仍可读取，超限内容不打开读取。"""
    path = tmp_path / "limited.txt"
    path.write_bytes(b"abcd")
    provider = FileSystemProvider(Repository.from_path(tmp_path), max_file_size=4)
    assert provider.read_text(path) == "abcd"
    path.write_bytes(b"abcde")

    def fail_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("超限文件不应打开")

    monkeypatch.setattr(Path, "open", fail_open)
    assert provider.read_text(path) is None


def test_missing_and_unreadable_files_return_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真正的读取错误继续遵守 Provider 的空结果契约。"""
    provider = FileSystemProvider(Repository.from_path(tmp_path))
    assert provider.read_text(tmp_path / "missing.txt") is None
    path = tmp_path / "unreadable.txt"
    path.write_text("content\n", encoding="utf-8")

    def deny_open(*args: object, **kwargs: object) -> None:
        raise PermissionError("read denied")

    monkeypatch.setattr(Path, "open", deny_open)
    assert provider.read_text(path) is None
