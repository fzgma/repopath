"""仓库分析配置测试。"""

from pathlib import Path

import pytest

from repopath.core.config import AnalysisConfigError, ensure_default_config, load_analysis_options
from repopath.core.service import analyze_repository


def test_toml_config_controls_scan_analyzers_git_and_report(tmp_path: Path) -> None:
    """验证 TOML 配置可覆盖默认分析选项。"""
    (tmp_path / ".repopath.toml").write_text(
        """
[scan]
profile = "deep"
max_file_size = 4096
follow_symlinks = true
exclude = ["generated/*", "*.min.js"]

[analyzers]
cpp = false

[git]
period = "90"

[report]
limit = 25
reading_limit = 8
include_file_list = true
""".strip(),
        encoding="utf-8",
    )

    options = load_analysis_options(tmp_path)

    assert options.max_file_size == 4096
    assert options.follow_symlinks is True
    assert options.excluded_patterns == ("generated/*", "*.min.js")
    assert options.cpp_enabled is False
    assert options.git_period == "90"
    assert options.result_limit == 25
    assert options.reading_limit == 8
    assert options.include_file_list is True


def test_ensure_default_config_creates_a_readable_template(tmp_path: Path) -> None:
    """验证默认配置文件会被创建并能立即读取。"""
    path = ensure_default_config(tmp_path)

    assert path == tmp_path / ".repopath.toml"
    assert "reading_limit = 10" in path.read_text(encoding="utf-8")
    assert load_analysis_options(tmp_path).include_file_list is False


def test_default_config_keeps_profile_analyzer_matrix_in_control(tmp_path: Path) -> None:
    """验证默认模板不会用显式 Analyzer 开关覆盖 profile。"""
    path = ensure_default_config(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('profile = "deep"', 'profile = "fast"'), encoding="utf-8")

    options = load_analysis_options(tmp_path)

    assert options.profile == "fast"
    assert options.python_enabled is False
    assert options.dependencies_enabled is False


def test_invalid_toml_config_reports_a_config_error(tmp_path: Path) -> None:
    """验证无效 TOML 会返回明确配置错误。"""
    (tmp_path / ".repopath.toml").write_text("[scan\n", encoding="utf-8")

    with pytest.raises(AnalysisConfigError, match="无法读取配置文件"):
        load_analysis_options(tmp_path)


def test_repository_analysis_applies_excludes_and_max_file_size(tmp_path: Path) -> None:
    """验证仓库分析会应用配置中的排除规则和文件大小限制。"""
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "ignored.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "large.py").write_text("x" * 100, encoding="utf-8")
    (tmp_path / ".repopath.toml").write_text(
        '[scan]\nmax_file_size = 32\nexclude = ["generated/*"]\n',
        encoding="utf-8",
    )

    report = analyze_repository(tmp_path)
    paths = {report.repository.relative_path(file.path) for file in report.files}

    assert "keep.py" in paths
    assert "generated/ignored.py" not in paths
    assert "large.py" not in paths


def test_disabling_dependencies_also_disables_default_insights(tmp_path: Path) -> None:
    """验证配置关闭依赖图时会同步关闭默认洞察分析。"""
    (tmp_path / ".repopath.toml").write_text(
        "[analyzers]\ndependencies = false\n",
        encoding="utf-8",
    )

    options = load_analysis_options(tmp_path)

    assert options.dependencies_enabled is False
    assert options.insights_enabled is False
