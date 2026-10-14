"""阅读指南的配置、CLI 和分析失败隔离验证。"""

import json
from pathlib import Path
from shutil import copytree

import pytest

from repopath.analyzer.python import PythonAnalyzer
from repopath.core.config import load_analysis_options
from repopath.core.service import analyze_repository
from repopath.interface import cli
from repopath.model.options import AnalysisOptions
from repopath.model.result import AnalysisResult, AnalyzerName

FIXTURE = Path(__file__).parent / "fixtures" / "reading_repo"


def test_reading_option_is_independent_of_profiles_and_languages(
    tmp_path: Path,
) -> None:
    """配置可在无语言分析和无依赖图时启用指南，CLI 能显式关闭。"""
    (tmp_path / ".repopath.toml").write_text(
        '[scan]\nprofile = "fast"\n[analyzers]\nreading = true\n',
        encoding="utf-8",
    )
    assert load_analysis_options(tmp_path).reading_enabled
    parser = cli.build_parser()
    for profile in ("fast", "standard", "deep"):
        configured = cli._resolve_options(
            tmp_path, parser.parse_args([str(tmp_path), "--profile", profile]),
        )
        assert configured.reading_enabled
    disabled = cli._resolve_options(
        tmp_path, parser.parse_args([str(tmp_path), "--no-reading-guide"]),
    )
    assert not disabled.reading_enabled
    enabled = cli._resolve_options(
        tmp_path,
        parser.parse_args([
            str(tmp_path), "--reading-guide", "--no-python", "--no-cpp",
        ]),
    )
    assert enabled.reading_enabled
    assert not enabled.dependencies_enabled


def test_cli_guide_works_without_dependency_graph(
    tmp_path: Path,
) -> None:
    """真实 CLI 在仅文件扫描模式输出文档证据与陌生语言的缺口。"""
    repository = tmp_path / "library"
    copytree(FIXTURE, repository)
    output = tmp_path / "report.json"
    assert cli.main([
        str(repository), "--profile", "fast", "--reading-guide",
        "--format", "json", "-o", str(output),
    ]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["analysis"]["analyzers"]["dependencies"]["status"] == "not_run"
    assert payload["reading_guide"]["status"] == "completed"
    assert payload["reading_guide"]["steps"]
    assert payload["reading_guide"]["gaps"]
    for step in payload["reading_guide"]["steps"]:
        assert not Path(step["location"]["path"]).is_absolute()
        assert step["evidence"]


def test_language_failure_does_not_discard_document_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """语言提供器失败仍保留文档指南，旧依赖评分不能假装成功。"""
    copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    monkeypatch.setattr(
        PythonAnalyzer, "analyze",
        lambda self, context, state: AnalysisResult(
            AnalyzerName.PYTHON, errors=["language provider unavailable"],
        ),
    )
    report = analyze_repository(
        tmp_path, options=AnalysisOptions(reading_enabled=True, git_enabled=False),
    )
    assert not report.analyzer_result(AnalyzerName.PYTHON).successful
    assert not report.analyzer_result(AnalyzerName.INSIGHTS).successful
    assert report.analyzer_result(AnalyzerName.READING).successful
    assert report.reading_guide.steps
    assert report.reading_guide.gaps


def test_default_mode_does_not_enable_experimental_guide(tmp_path: Path) -> None:
    """尚未经独立阅读验收的机制不会静默替换默认输出。"""
    report = analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))
    assert report.analyzer_result(AnalyzerName.READING).status == "not_run"
    assert not report.reading_guide.steps
