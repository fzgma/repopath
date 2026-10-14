"""`.repopath.toml` 配置加载。"""

from pathlib import Path
import tomllib
from typing import cast

from ..model.options import AnalysisOptions


DEFAULT_CONFIG_NAME = ".repopath.toml"
DEFAULT_CONFIG_TEXT = """# RepoPath 仓库分析配置

[scan]
profile = "deep"
max_file_size = 2097152
follow_symlinks = false
exclude = []

[analyzers]
# 可选：显式覆盖 profile 中的单项开关，例如：
# python = false
# cpp = false
# git = false
# dependencies = false
# insights = false

[cpp]
backend = "basic"
# libclang 模式需要编译数据库，路径相对仓库根目录：
# compile_commands = "build/compile_commands.json"

[git]
period = "all"

[github]
archive_max_mb = 100
file_limit = 10000
content_max_mb = 100
file_max_mb = 10

[report]
limit = 50
reading_limit = 10
include_file_list = false
"""


class AnalysisConfigError(ValueError):
    """表示仓库分析配置无法读取或校验。"""


def config_path_for(
    root: Path, config_path: str | Path | None = None
) -> Path:
    """解析仓库配置文件的绝对路径。"""
    if config_path:
        candidate = Path(config_path).expanduser()
        return (
            candidate if candidate.is_absolute() else root / candidate
        ).resolve()
    return root / DEFAULT_CONFIG_NAME


def ensure_default_config(root: Path) -> Path:
    """在仓库根目录缺少配置时创建默认 TOML 文件。"""
    path = config_path_for(root)
    if path.exists():
        return path
    try:
        path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    except OSError as exc:
        raise AnalysisConfigError(
            f"无法创建默认配置文件 {path}：{exc}"
        ) from exc
    return path


def load_analysis_options(
    root: Path,
    config_path: str | Path | None = None,
) -> AnalysisOptions:
    """从仓库配置文件加载分析选项。"""
    path = config_path_for(root, config_path)
    if not path.exists():
        return AnalysisOptions()
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise AnalysisConfigError(
            f"无法读取配置文件 {path}：{exc}"
        ) from exc

    scan = _section(payload, "scan")
    analyzers = _section(payload, "analyzers")
    cpp = _section(payload, "cpp")
    git = _section(payload, "git")
    github = _section(payload, "github")
    report = _section(payload, "report")
    profile = str(scan.get("profile", "deep"))
    python_enabled = _optional_bool(analyzers, "python")
    cpp_enabled = _optional_bool(analyzers, "cpp")
    dependencies_enabled = _optional_bool(analyzers, "dependencies")
    insights_enabled = _optional_bool(analyzers, "insights")
    preset = AnalysisOptions.for_profile(profile)
    effective_python = (
        preset.python_enabled
        if python_enabled is None
        else python_enabled
    )
    effective_cpp = (
        preset.cpp_enabled if cpp_enabled is None else cpp_enabled
    )
    if dependencies_enabled is False or (
        not effective_python and not effective_cpp
    ):
        dependencies_enabled = False
        if insights_enabled is None:
            insights_enabled = False
    try:
        options = preset.with_overrides(
            max_file_size=_optional_int(scan, "max_file_size"),
            follow_symlinks=_optional_bool(scan, "follow_symlinks"),
            excluded_patterns=_optional_strings(scan, "exclude"),
            python_enabled=python_enabled,
            cpp_enabled=cpp_enabled,
            cpp_backend=_optional_string(cpp, "backend"),
            cpp_compile_commands=_optional_string(cpp, "compile_commands"),
            git_enabled=_optional_bool(analyzers, "git"),
            dependencies_enabled=dependencies_enabled,
            insights_enabled=insights_enabled,
            git_period=str(git["period"]) if "period" in git else None,
            github_archive_max_bytes=_megabytes_to_bytes(
                github, "archive_max_mb"
            ),
            github_file_limit=_optional_int(github, "file_limit"),
            github_content_max_bytes=_megabytes_to_bytes(
                github, "content_max_mb"
            ),
            github_file_max_bytes=_megabytes_to_bytes(
                github, "file_max_mb"
            ),
            result_limit=_optional_int(report, "limit"),
            reading_limit=_optional_int(report, "reading_limit"),
            include_file_list=_optional_bool(
                report, "include_file_list"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise AnalysisConfigError(
            f"配置文件 {path} 无效：{exc}"
        ) from exc
    return options


def _section(
    payload: dict[str, object], name: str
) -> dict[str, object]:
    """读取并校验一个 TOML 表。"""
    value = payload.get(name, {})
    if not isinstance(value, dict):
        raise AnalysisConfigError(f"配置项 [{name}] 必须是 TOML 表")
    return cast(dict[str, object], value)


def _optional_string(section: dict[str, object], key: str) -> str | None:
    """读取可选字符串配置，避免将无效类型隐式转换为路径。"""
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} 必须是字符串")
    return value


def _optional_bool(section: dict[str, object], key: str) -> bool | None:
    """读取可选布尔配置。"""
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} 必须是布尔值")
    return value


def _optional_int(section: dict[str, object], key: str) -> int | None:
    """读取可选整数配置。"""
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{key} 必须是整数")
    return value


def _megabytes_to_bytes(
    section: dict[str, object], key: str
) -> int | None:
    """读取 MB 配置并转换为字节数。"""
    megabytes = _optional_int(section, key)
    return megabytes * 1024 * 1024 if megabytes is not None else None


def _optional_strings(
    section: dict[str, object], key: str
) -> tuple[str, ...] | None:
    """读取可选字符串数组配置。"""
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} 必须是字符串数组")
    strings: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise TypeError(f"{key} 必须是字符串数组")
        strings.append(item)
    return tuple(strings)
