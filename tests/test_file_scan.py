"""二进制过滤对统计、命令行及 Streamlit 的一致性测试。"""

import json
import sqlite3
from pathlib import Path
from time import monotonic, sleep
from typing import IO

import pytest
from streamlit.testing.v1 import AppTest

from repopath.core.service import analyze_repository
from repopath.interface import cli
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.result import AnalyzerName
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


def _create_mixed_files(root: Path) -> None:
    """准备源码、文档、Unicode 文本及容易污染统计的资源文件。"""
    (root / "app.py").write_text("# sample\nvalue = 1\n\n", encoding="utf-8")
    (root / "README.md").write_text("# Sample\n\nDetails.\n", encoding="utf-8")
    (root / "settings.db").write_text("enabled=true\n", encoding="utf-8")
    (root / "notes").write_bytes("第一行\r\n第二行\r\n".encode("utf-16"))
    assets = root / "assets"
    assets.mkdir()
    (assets / "icon.svg").write_text("<svg/>\n", encoding="utf-8")
    (assets / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00image\n" * 100)
    (assets / "pretend.cpp").write_bytes(b"\x00\x01\x02\x03\n" * 100)
    connection = sqlite3.connect(root / "storage.py")
    try:
        connection.execute("CREATE TABLE notes (body TEXT)")
        connection.execute("INSERT INTO notes VALUES (?)", ("text\n" * 100,))
        connection.commit()
    finally:
        connection.close()


def test_binary_files_do_not_pollute_counts_or_language_analysis(
    tmp_path: Path,
) -> None:
    """完整流水线和两种导出只统计可读取文本，二进制不进入源码分析。"""
    _create_mixed_files(tmp_path)
    options = AnalysisOptions.for_profile("standard").with_overrides(
        git_enabled=False, include_file_list=True,
    )
    report = analyze_repository(tmp_path, options=options)
    paths = {report.repository.relative_path(item.path) for item in report.files}

    assert paths == {"app.py", "README.md", "settings.db", "notes", "assets/icon.svg"}
    assert report.stats.total_non_empty_lines == 8
    assert report.stats.language_family_counts == {"Python": 1, "Markdown": 1, "Other": 3}
    assert report.stats.directory_counts == {".": 4, "assets": 1}
    assert report.stats.directory_lines == {".": 7, "assets": 1}
    assert not report.errors
    assert report.analyzer_result(AnalyzerName.PYTHON).successful
    assert not report.analyzer_result(AnalyzerName.PYTHON).warnings
    assert not report.cpp.files
    scan = report.analyzer_result(AnalyzerName.FILES)
    assert scan.successful
    assert len(scan.warnings) == 1
    assert "3" in scan.warnings[0] and "跳过" in scan.warnings[0]

    payload = json.loads(JsonRenderer().render(report))
    assert payload["overview"]["file_count"] == 5
    assert payload["overview"]["non_empty_lines"] == 8
    assert payload["directory_stats"]["assets"] == {"files": 1, "non_empty_lines": 1}
    assert {item["path"] for item in payload["files"]} == paths
    for detail in ("summary", "full"):
        markdown = MarkdownRenderer().render(report, detail=detail)
        assert "- 文件数：5" in markdown
        assert "- 非空行数：8" in markdown
        assert "storage.py" not in markdown
        assert "pretend.cpp" not in markdown


def test_skipped_files_produce_one_summary_instead_of_one_error_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """二进制、未知编码、超限和读取失败只产生一个诚实的汇总提示。"""
    (tmp_path / "keep.txt").write_bytes(b"keep\n")
    for index in range(30):
        (tmp_path / f"image-{index}.png").write_bytes(b"\x89PNG\x00\n")
    (tmp_path / "legacy.txt").write_bytes("中文".encode("gbk"))
    (tmp_path / "large.txt").write_bytes(b"a" * 65)
    unreadable = tmp_path / "unreadable.txt"
    unreadable.write_bytes(b"text")
    original_open = Path.open

    def open_file(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[str] | IO[bytes]:
        if path == unreadable:
            raise PermissionError("read denied")
        return original_open(
            path, mode, buffering, encoding, errors, newline,
        )

    monkeypatch.setattr(Path, "open", open_file)
    report = analyze_repository(
        tmp_path,
        options=AnalysisOptions.for_profile("fast").with_overrides(max_file_size=64),
    )

    assert len(report.files) == 1
    assert report.stats.total_non_empty_lines == 1
    assert not report.errors
    warnings = report.analyzer_result(AnalyzerName.FILES).warnings
    assert len(warnings) == 1
    assert "33" in warnings[0] and "跳过" in warnings[0]
    assert "非文本" in warnings[0]
    assert "编码" in warnings[0]


def test_repository_containing_only_binary_files_has_zero_text_statistics(
    tmp_path: Path,
) -> None:
    """只有资源文件的仓库仍可成功分析，不捏造 Other 文本行。"""
    (tmp_path / "image").write_bytes(b"\x89PNG\r\n\x1a\n\x00data")
    report = analyze_repository(tmp_path, options=AnalysisOptions.for_profile("fast"))
    payload = json.loads(JsonRenderer().render(report))

    assert report.analyzer_result(AnalyzerName.FILES).successful
    assert report.analyzer_result(AnalyzerName.STATISTICS).successful
    assert payload["overview"]["file_count"] == 0
    assert payload["overview"]["non_empty_lines"] == 0
    assert payload["languages"] == {}
    assert payload["directories"] == {}


def test_ui_and_cli_share_binary_filtering_and_text_statistics(tmp_path: Path) -> None:
    """从实际 UI 启动分析并与 CLI 导出比较，防止两端统计口径分离。"""
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_mixed_files(repository)
    (repository / ".repopath.toml").write_text(
        '[scan]\nprofile = "fast"\n', encoding="utf-8",
    )
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=10)
    assert not app.exception
    app.text_input[0].set_value(str(repository)).run(timeout=10)
    next(item for item in app.button if item.label == "分析仓库").click()
    app.run(timeout=20)
    deadline = monotonic() + 10
    while not any(item.label == "报告视图" for item in app.segmented_control):
        assert not app.exception
        if monotonic() >= deadline:
            pytest.fail("Streamlit 后台分析未能在测试时限内完成")
        sleep(0.05)
        app.run(timeout=10)

    report = app.session_state["repopath.analysis_runtime"].snapshot().report
    assert isinstance(report, RepositoryReport)
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["文件数"] == "5"
    assert metrics["非空行"] == "8"
    output = tmp_path / "cli-report.json"
    assert cli.main([str(repository), "-o", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    ui_payload = json.loads(JsonRenderer().render(report))
    for field in ("file_count", "non_empty_lines", "language_count", "comment_lines"):
        assert payload["overview"][field] == ui_payload["overview"][field]
    for field in ("languages", "directories", "directory_stats", "files", "warnings"):
        assert payload[field] == ui_payload[field]
