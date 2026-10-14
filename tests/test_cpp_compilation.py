"""编译数据库只读加载、参数语义保留与不支持配置的契约。"""

import json
import os
from pathlib import Path

import pytest

from repopath.analyzer.cpp.compilation import (
    CompilationDatabaseError,
    find_compilation_database,
    normalize_arguments,
    read_compilation_database,
)


def test_arguments_preserve_semantics_and_resolve_directory(tmp_path: Path) -> None:
    """保留影响语义的参数，按条目目录解析路径并移除输出选项。"""
    source = tmp_path / "source.cpp"
    before = Path.cwd()
    result = normalize_arguments(
        [
            "clang++",
            "-I",
            "include dir",
            "-isystemheaders",
            "-include",
            "config.hpp",
            "-D",
            "ENABLED=1",
            "-std=c++20",
            "--target=x86_64-pc-linux-gnu",
            "-c",
            "source.cpp",
            "-o",
            "ignored.o",
            "-MMD",
            "-MFdeps.d",
        ],
        tmp_path,
        source,
    )
    assert Path.cwd() == before
    assert result == (
        "-I",
        str(tmp_path / "include dir"),
        "-isystem",
        str(tmp_path / "headers"),
        "-include",
        str(tmp_path / "config.hpp"),
        "-D",
        "ENABLED=1",
        "-std=c++20",
        "--target=x86_64-pc-linux-gnu",
    )
    assert not (tmp_path / "ignored.o").exists()


@pytest.mark.parametrize(
    "flag",
    [
        "@args.rsp",
        "-fplugin=evil.so",
        "-Xclang",
        "--config=evil.cfg",
        "--driver-mode=cl",
        "-specs=evil.specs",
        "-Btools",
        "-include-pch",
        "-unknown-flag",
        "-Wp,-include,evil.h",
    ],
)
def test_unsupported_or_code_loading_arguments_are_rejected(
    tmp_path: Path, flag: str
) -> None:
    """拒绝插件加载、隐式配置和超出支持范围的参数。"""
    with pytest.raises(CompilationDatabaseError):
        normalize_arguments(
            ["clang++", flag, "source.cpp"], tmp_path, tmp_path / "source.cpp"
        )


def test_arguments_take_precedence_and_duplicate_commands_are_removed(
    tmp_path: Path,
) -> None:
    """优先读取结构化参数，并将完全相同的编译条目去重。"""
    record = {
        "directory": str(tmp_path),
        "file": "source.cpp",
        "arguments": ["clang++", "-c", "source.cpp"],
        "command": "this command must never be interpreted",
    }
    path = tmp_path / "compile_commands.json"
    path.write_text(json.dumps([record, record]), encoding="utf-8")
    units = read_compilation_database(path)
    assert len(units) == 1
    assert units[0].path == tmp_path / "source.cpp"
    assert units[0].reason is None


def test_multiple_configurations_for_one_source_are_rejected(tmp_path: Path) -> None:
    """拒绝混合单个源文件的不同配置，防止合并互斥语义事实。"""
    records = [
        {
            "directory": str(tmp_path),
            "file": "source.cpp",
            "arguments": ["clang++", f"-DVARIANT={number}", "source.cpp"],
        }
        for number in (1, 2)
    ]
    path = tmp_path / "compile_commands.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    units = read_compilation_database(path)
    assert len(units) == 2
    assert all(
        unit.status == "failed" and "多个不同编译配置" in (unit.reason or "")
        for unit in units
    )


def test_command_strings_are_parsed_only_on_supported_platforms(tmp_path: Path) -> None:
    """只解析支持的命令引号规则，Windows 要求 arguments 数组。"""
    path = tmp_path / "compile_commands.json"
    path.write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "source file.cpp",
                    "command": "clang++ '-DVALUE=two words' -c 'source file.cpp'",
                }
            ]
        ),
        encoding="utf-8",
    )
    unit = read_compilation_database(path)[0]
    if os.name == "nt":
        assert unit.status == "failed"
        assert "Windows" in (unit.reason or "")
    else:
        assert unit.arguments == ("-DVALUE=two words",)
        assert unit.reason is None


def test_database_search_and_explicit_path_are_predictable(tmp_path: Path) -> None:
    """区分默认发现、显式指定、缺失文件和空编译数据库。"""
    build = tmp_path / "build"
    build.mkdir()
    path = build / "compile_commands.json"
    path.write_text("[]", encoding="utf-8")
    assert find_compilation_database(tmp_path, None) == path
    assert find_compilation_database(tmp_path, "build") == path
    with pytest.raises(CompilationDatabaseError, match="不存在"):
        find_compilation_database(tmp_path, "missing.json")
    with pytest.raises(CompilationDatabaseError, match="非空"):
        read_compilation_database(path)
