"""语言识别测试。"""

from pathlib import Path

from repopath.model.language import (
    Language,
    detect_language,
    language_family,
)


def test_cpp_source_and_header_extensions_are_supported() -> None:
    """验证常见 C++ 源文件和头文件扩展名可被识别。"""
    for suffix in (".cpp", ".cc", ".cxx"):
        assert detect_language(Path(f"sample{suffix}")) is Language.CPP
    for suffix in (".h", ".hpp", ".hh", ".hxx"):
        assert (
            detect_language(Path(f"sample{suffix}"))
            is Language.CPP_HEADER
        )
    assert language_family(Language.CPP_HEADER) == "C++"
