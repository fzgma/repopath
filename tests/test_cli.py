"""命令行入口测试。"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from repopath.interface import cli
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository, RepositorySource
from repopath.model.result import AnalysisProgress


def _install_fake_analysis(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[Path, set[Path], AnalysisOptions]],
) -> None:
    """替换仓库分析服务并记录 CLI 传入的参数。"""

    def fake_analyze_repository(
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None = None,
        options: AnalysisOptions | None = None,
        progress_callback: Callable[[AnalysisProgress], None] | None = None,
    ) -> RepositoryReport:
        """返回最小报告以隔离 CLI 的参数和输出逻辑。"""
        assert isinstance(path, Path)
        assert options is not None
        calls.append((path, excluded_paths or set(), options))
        return RepositoryReport(repository=Repository.from_path(path), options=options)

    monkeypatch.setattr(cli, "analyze_repository", fake_analyze_repository)


def test_cli_writes_markdown_and_passes_options_to_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """验证 Markdown 输出路径会被排除且 CLI 参数传给分析服务。"""
    calls: list[tuple[Path, set[Path], AnalysisOptions]] = []
    _install_fake_analysis(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(
        [
            ".",
            "-o",
            "reports/custom.md",
            "--profile",
            "standard",
            "--exclude",
            "build/*",
            "--max-file-size",
            "4096",
            "--result-limit",
            "12",
            "--no-git",
        ]
    )

    output = tmp_path / "reports" / "custom.md"
    assert exit_code == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8").startswith("# RepoPath 报告")
    assert "报告已写入" in capsys.readouterr().out
    assert len(calls) == 1
    root, excluded_paths, options = calls[0]
    assert root == tmp_path
    assert excluded_paths == {output.resolve()}
    assert options.profile == "standard"
    assert options.git_enabled is False
    assert options.dependencies_enabled is False
    assert options.insights_enabled is False
    assert options.max_file_size == 4096
    assert options.result_limit == 12
    assert options.excluded_patterns == ("build/*",)


def test_cli_uses_json_default_output_when_format_is_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 JSON 格式会将默认输出名切换为 JSON 文件。"""
    calls: list[tuple[Path, set[Path], AnalysisOptions]] = []
    _install_fake_analysis(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    assert cli.main([".", "--format", "json"]) == 0

    output = tmp_path / "REPOPATH_REPORT.json"
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert not (tmp_path / "REPOPATH_REPORT.md").exists()
    assert payload["repository"]["root"] == str(tmp_path)
    assert calls[0][1] == {output.resolve()}


def test_cli_generates_and_reads_missing_default_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 CLI 会创建缺失的默认配置文件并将其传入分析服务。"""
    calls: list[tuple[Path, set[Path], AnalysisOptions]] = []
    _install_fake_analysis(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["."]) == 0

    config = tmp_path / ".repopath.toml"
    assert config.exists()
    assert "include_file_list = false" in config.read_text(encoding="utf-8")
    assert calls[0][2].reading_limit == 10
    assert calls[0][2].include_file_list is False


def test_resolve_options_gives_cli_priority_over_profile_and_config(tmp_path: Path) -> None:
    """验证 CLI 参数可覆盖预设模式和仓库配置中的选项。"""
    (tmp_path / ".repopath.toml").write_text(
        """
[scan]
max_file_size = 256
exclude = ["generated/*"]

[analyzers]
git = true
cpp = false

[git]
period = "90"

[report]
limit = 20
""".strip(),
        encoding="utf-8",
    )
    args = cli.build_parser().parse_args(
        [
            ".",
            "--profile",
            "standard",
            "--exclude",
            "build/*",
            "--no-cpp",
            "--git-period",
            "30",
            "--result-limit",
            "6",
        ]
    )

    options = cli._resolve_options(tmp_path, args)

    assert options.profile == "standard"
    assert options.python_enabled is True
    assert options.cpp_enabled is False
    assert options.git_enabled is True
    assert options.dependencies_enabled is False
    assert options.insights_enabled is False
    assert options.max_file_size == 256
    assert options.git_period == "30"
    assert options.result_limit == 6
    assert options.excluded_patterns == ("generated/*", "build/*")


def test_resolve_options_disables_dependency_features_without_languages(tmp_path: Path) -> None:
    """验证关闭两种语言时会同步关闭依赖和阅读洞察。"""
    args = cli.build_parser().parse_args([".", "--no-python", "--no-cpp"])

    options = cli._resolve_options(tmp_path, args)

    assert options.python_enabled is False
    assert options.cpp_enabled is False
    assert options.dependencies_enabled is False
    assert options.insights_enabled is False


def test_cli_reports_missing_repository_as_argument_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """验证不存在的仓库目录会由 argparse 以参数错误形式报告。"""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="2"):
        cli.main(["missing"])

    assert "仓库目录不存在" in capsys.readouterr().err
