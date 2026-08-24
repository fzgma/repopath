"""`.repopath.toml` 配置加载。"""

from pathlib import Path
import tomllib
from typing import cast

from ..model.options import AnalysisOptions


class AnalysisConfigError(ValueError):
    """表示仓库分析配置无法读取或校验。"""


def load_analysis_options(
    root: Path,
    config_path: str | Path | None = None,
) -> AnalysisOptions:
    """从仓库配置文件加载分析选项。"""
    if config_path:
        candidate = Path(config_path).expanduser()
        path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    else:
        path = root / ".repopath.toml"
    if not path.exists():
        return AnalysisOptions()
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise AnalysisConfigError(f"无法读取配置文件 {path}：{exc}") from exc

    scan = _section(payload, "scan")
    analyzers = _section(payload, "analyzers")
    git = _section(payload, "git")
    report = _section(payload, "report")
    profile = str(scan.get("profile", "deep"))
    python_enabled = _optional_bool(analyzers, "python")
    cpp_enabled = _optional_bool(analyzers, "cpp")
    dependencies_enabled = _optional_bool(analyzers, "dependencies")
    insights_enabled = _optional_bool(analyzers, "insights")
    preset = AnalysisOptions.for_profile(profile)
    effective_python = preset.python_enabled if python_enabled is None else python_enabled
    effective_cpp = preset.cpp_enabled if cpp_enabled is None else cpp_enabled
    if dependencies_enabled is False or (not effective_python and not effective_cpp):
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
            git_enabled=_optional_bool(analyzers, "git"),
            dependencies_enabled=dependencies_enabled,
            insights_enabled=insights_enabled,
            git_period=str(git["period"]) if "period" in git else None,
            result_limit=_optional_int(report, "limit"),
        )
    except (TypeError, ValueError) as exc:
        raise AnalysisConfigError(f"配置文件 {path} 无效：{exc}") from exc
    return options


def _section(payload: dict[str, object], name: str) -> dict[str, object]:
    """读取并校验一个 TOML 表。"""
    value = payload.get(name, {})
    if not isinstance(value, dict):
        raise AnalysisConfigError(f"配置项 [{name}] 必须是 TOML 表")
    return cast(dict[str, object], value)


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


def _optional_strings(section: dict[str, object], key: str) -> tuple[str, ...] | None:
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
