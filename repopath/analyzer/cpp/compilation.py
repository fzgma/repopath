"""只读解析编译数据库并将支持的参数归一化，不执行构建命令。"""

import json
import os
import re
import shlex
from pathlib import Path

from ...model.cpp import CppTranslationUnit


class CompilationDatabaseError(ValueError):
    """表示缺失、不合法或超出 POC 支持范围的编译配置。"""


def find_compilation_database(root: Path, configured: str | None) -> Path:
    """定位显式数据库或仓库根目录、build 下的默认数据库。"""
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            path = path / "compile_commands.json"
        if path.is_file():
            return path.resolve()
        raise CompilationDatabaseError(f"编译数据库不存在：{path}")
    for path in (
        root / "compile_commands.json",
        root / "build" / "compile_commands.json",
    ):
        if path.is_file():
            return path.resolve()
    raise CompilationDatabaseError(
        "libclang 后端需要 compile_commands.json；未找到编译数据库"
    )


def _absolute(value: str, directory: Path) -> str:
    """按编译条目的工作目录解析相对路径，不更改进程工作目录。"""
    path = Path(value)
    return str((path if path.is_absolute() else directory / path).resolve())


def normalize_arguments(
    arguments: list[str], directory: Path, source: Path
) -> tuple[str, ...]:
    """保留解析语义参数，移除编译产物参数并拒绝插件和隐式命令。"""
    if not arguments or not all(isinstance(item, str) and item for item in arguments):
        raise CompilationDatabaseError("arguments 必须是包含编译器名称的非空字符串列表")
    if any(item.startswith("@") or "\x00" in item for item in arguments[1:]):
        raise CompilationDatabaseError("POC 不支持响应文件或包含 NUL 的参数")
    compiler = Path(arguments[0]).name.lower()
    if not re.fullmatch(
        r"(?:clang\+\+|clang|g\+\+|gcc|c\+\+|cc)(?:-\d+(?:\.\d+)*)?(?:\.exe)?", compiler
    ):
        raise CompilationDatabaseError(
            f"POC 仅支持 Clang/GCC 风格 arguments，不支持该驱动或 wrapper：{compiler}"
        )
    result: list[str] = []
    path_options = (
        "-isystem",
        "-iquote",
        "-idirafter",
        "-include",
        "-imacros",
        "-isysroot",
        "--sysroot",
        "-resource-dir",
        "-iframework",
        "-I",
        "-F",
    )
    output_options = ("-o", "-MF", "-MT", "-MQ", "-MJ", "--serialize-diagnostics")
    value_options = {"-D", "-U", "-x", "-std", "-target", "--target", "-arch"}
    skip_flags = {"-c", "-S", "-fsyntax-only", "-MD", "-MMD", "-MP", "-MG", "-M", "-MM"}
    semantic_flags = {
        "-nostdinc",
        "-nostdinc++",
        "-nostdlibinc",
        "-nobuiltininc",
        "-fexceptions",
        "-fno-exceptions",
        "-frtti",
        "-fno-rtti",
        "-fms-extensions",
        "-fms-compatibility",
        "-fdelayed-template-parsing",
        "-fno-delayed-template-parsing",
        "-pthread",
        "-m32",
        "-m64",
        "-ansi",
        "-fPIC",
        "-fpic",
        "-fPIE",
        "-fpie",
        "-fvisibility-inlines-hidden",
        "-fno-omit-frame-pointer",
        "-fomit-frame-pointer",
        "-fno-strict-aliasing",
        "-fstrict-aliasing",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
        "-w",
        "-pedantic",
    }
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if (
            argument.startswith(
                (
                    "@",
                    "-fplugin",
                    "-fpass-plugin",
                    "-load",
                    "-Xclang",
                    "-Xpreprocessor",
                    "-Wp,",
                    "-save-temps",
                    "--config",
                    "--driver-mode",
                    "-specs",
                    "--specs",
                    "-B",
                    "-include-pch",
                    "-working-directory=",
                )
            )
            or argument in {"-cc1", "-cc1as", "-working-directory"}
            or argument in {"&&", "||", ";", "|", ">", "<"}
        ):
            raise CompilationDatabaseError(
                f"POC 拒绝插件、响应文件或不受支持的命令参数：{argument}"
            )
        if argument in skip_flags:
            continue
        if argument in output_options:
            if index >= len(arguments):
                raise CompilationDatabaseError(f"编译参数缺少取值：{argument}")
            index += 1
            continue
        if any(
            argument.startswith(option) and argument != option
            for option in output_options
        ):
            continue
        matched_path = next(
            (
                option
                for option in path_options
                if argument == option
                or argument.startswith(option + "=")
                or (
                    option.startswith("-")
                    and not option.startswith("--")
                    and argument.startswith(option)
                    and argument != option
                )
            ),
            None,
        )
        if matched_path:
            if argument == matched_path:
                if index >= len(arguments):
                    raise CompilationDatabaseError(f"编译参数缺少路径：{argument}")
                value = arguments[index]
                index += 1
            else:
                value = argument[len(matched_path) :].removeprefix("=")
            if not value:
                raise CompilationDatabaseError(f"编译参数缺少路径：{argument}")
            resolved = _absolute(value, directory)
            if matched_path == "--sysroot":
                result.append("--sysroot=" + resolved)
            else:
                result.extend((matched_path, resolved))
            continue
        if argument in value_options:
            if index >= len(arguments):
                raise CompilationDatabaseError(f"编译参数缺少取值：{argument}")
            result.extend((argument, arguments[index]))
            index += 1
            continue
        if argument.startswith("-"):
            if (
                argument in semantic_flags
                or argument.startswith(
                    (
                        "-D",
                        "-U",
                        "-std=",
                        "--std=",
                        "--target=",
                        "-target=",
                        "-Wno-",
                        "-Werror=",
                        "-march=",
                        "-mcpu=",
                        "-fvisibility=",
                    )
                )
                or re.fullmatch(
                    r"-O(?:[0123sgz]|fast)?|-g(?:[0-3]|gdb[0-3]?)?", argument
                )
            ):
                result.append(argument)
                continue
            raise CompilationDatabaseError(f"POC 不支持该编译参数：{argument}")
        if Path(_absolute(argument, directory)) == source:
            continue
        raise CompilationDatabaseError(
            f"不支持额外的源文件、链接输入或命令参数：{argument}"
        )
    return tuple(result)


def read_compilation_database(path: Path) -> list[CppTranslationUnit]:
    """读取数据库；条目参数错误独立保留，允许其他 TU 继续解析。"""
    try:
        records = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CompilationDatabaseError(f"无法读取编译数据库：{exc}") from exc
    if not isinstance(records, list) or not records:
        raise CompilationDatabaseError("编译数据库必须是非空 JSON 数组")
    units: list[CppTranslationUnit] = []
    seen: set[tuple[Path, tuple[str, ...]]] = set()
    for number, record in enumerate(records, start=1):
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("file"), str)
            or not record["file"]
        ):
            raise CompilationDatabaseError(f"编译数据库第 {number} 项缺少有效 file")
        raw_directory = record.get("directory")
        if not isinstance(raw_directory, str) or not raw_directory:
            raise CompilationDatabaseError(
                f"编译数据库第 {number} 项缺少有效 directory"
            )
        directory = Path(_absolute(raw_directory, path.parent))
        source = Path(_absolute(record["file"], directory))
        unit = CppTranslationUnit(path=source, directory=directory)
        try:
            if not directory.is_dir():
                raise CompilationDatabaseError(f"编译工作目录不存在：{directory}")
            if "arguments" in record:
                arguments = record["arguments"]
                if not isinstance(arguments, list):
                    raise CompilationDatabaseError("arguments 必须是字符串列表")
            else:
                command = record.get("command")
                if not isinstance(command, str) or not command:
                    raise CompilationDatabaseError("条目需要 arguments 或 command")
                if os.name == "nt":
                    raise CompilationDatabaseError(
                        "Windows 的 command 字符串暂不支持；请提供 arguments 数组"
                    )
                if any(marker in command for marker in ("$", "`", "\n", "\r")):
                    raise CompilationDatabaseError(
                        "command 包含不支持的 shell 展开或多行命令"
                    )
                arguments = shlex.split(command, posix=True)
            unit.arguments = normalize_arguments(arguments, directory, source)
        except (CompilationDatabaseError, ValueError) as exc:
            unit.status = "failed"
            unit.reason = str(exc)
        key = (source, unit.arguments)
        if unit.status == "failed" or key not in seen:
            units.append(unit)
            seen.add(key)
    configurations: dict[Path, set[tuple[str, ...]]] = {}
    for unit in units:
        if unit.status != "failed":
            configurations.setdefault(unit.path, set()).add(unit.arguments)
    for unit in units:
        if len(configurations.get(unit.path, set())) > 1:
            unit.status = "failed"
            unit.reason = (
                "同一源文件存在多个不同编译配置；POC 不混合互斥配置，请提供单配置数据库"
            )
    return units
