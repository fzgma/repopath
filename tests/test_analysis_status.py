"""执行状态、profile 和报告聚合契约。"""

import json
from pathlib import Path

import pytest

from repopath.analyzer.dependency_analyzer import DependencyAnalyzer
from repopath.analyzer.file_analyzer import FileAnalyzer
from repopath.analyzer.git_analyzer import GitAnalyzer
from repopath.analyzer.python import PythonAnalyzer
from repopath.core.service import analyze_repository
from repopath.model.git import GitSummary
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository
from repopath.provider.git import GitProvider
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_repo"


@pytest.mark.parametrize("profile", ["fast", "standard", "deep"])
def test_profile_execution_matches_report(profile: str) -> None:
    report = analyze_repository(FIXTURE, options=AnalysisOptions.for_profile(profile))
    payload = json.loads(JsonRenderer().render(report))
    assert len(report.analyzer_results) == 7
    for name, result in report.analyzer_results.items():
        expected = "completed" if report.options.analyzer_enabled(name) else "not_run"
        assert result.status == expected
        assert payload["analysis"]["analyzers"][name]["status"] == expected
        assert (name in report.analyzer_durations) == (expected == "completed")
    for name in ("dependencies", "insights"):
        expected = "completed" if profile == "deep" else "not_run"
        assert payload[name]["status"] == expected
        for detail in ("full", "summary"):
            markdown = MarkdownRenderer().render(report, detail=detail)
            assert f"`{expected}`" in markdown
            if expected == "not_run":
                assert "profile=" + profile in markdown
                assert "未检测到循环依赖。" not in markdown
                assert "未检测到变更关注模块。" not in markdown
    assert payload["overview"]["dependency_nodes"] == (8 if profile == "deep" else None)


def test_local_edges_flow_into_graph_and_insights() -> None:
    report = analyze_repository(FIXTURE, options=AnalysisOptions.for_profile("deep"))
    graph_edges = {
        (edge.source, edge.target, edge.kind) for edge in report.dependencies.edges
    }
    for edge in report.python.dependencies:
        assert (
            f"python:{edge.source}",
            f"python:{edge.target}",
            edge.kind,
        ) in graph_edges
    for edge in report.cpp.dependencies:
        assert (f"cpp:{edge.source}", f"cpp:{edge.target}", edge.kind) in graph_edges
    assert {item.node_id for item in report.insights.module_scores} == set(
        report.dependencies.nodes
    )
    assert report.insights.reading_order


def test_dependency_failure_skips_insights(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("graph failed")

    monkeypatch.setattr(DependencyAnalyzer, "analyze", fail)
    events = []
    report = analyze_repository(FIXTURE, progress_callback=events.append)
    assert report.analyzer_results["dependencies"].status == "failed"
    assert report.analyzer_results["insights"].status == "not_run"
    assert "dependencies" in report.analyzer_results["insights"].reason
    assert events[-1].percent == 100
    payload = json.loads(JsonRenderer().render(report))
    assert payload["dependencies"]["status"] == "failed"
    assert payload["insights"]["status"] == "not_run"
    for detail in ("full", "summary"):
        markdown = MarkdownRenderer().render(report, detail=detail)
        assert "graph failed" in markdown
        assert "上游分析未完成：dependencies" in markdown
        assert "未检测到循环依赖。" not in markdown


def test_completed_empty_graph_is_not_not_run(tmp_path: Path) -> None:
    report = analyze_repository(tmp_path)
    payload = json.loads(JsonRenderer().render(report))
    assert payload["dependencies"]["status"] == "completed"
    assert payload["dependencies"]["nodes"] == []
    assert payload["overview"]["dependency_nodes"] == 0
    assert payload["insights"]["status"] == "completed"


def test_rendering_outputs_does_not_change_same_snapshot(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("value = 1\n", encoding="utf-8")
    outputs = {tmp_path / "report.json", tmp_path / "report.md"}
    report = analyze_repository(tmp_path, excluded_paths=outputs)
    (tmp_path / "report.json").write_text(
        JsonRenderer().render(report), encoding="utf-8"
    )
    (tmp_path / "report.md").write_text(
        MarkdownRenderer().render(report), encoding="utf-8"
    )
    again = analyze_repository(tmp_path, excluded_paths=outputs)
    assert report.files == again.files
    assert report.dependencies == again.dependencies
    assert report.insights == again.insights


def test_fast_entries_are_unknown_instead_of_zero() -> None:
    report = analyze_repository(FIXTURE, options=AnalysisOptions.for_profile("fast"))
    payload = json.loads(JsonRenderer().render(report))
    assert payload["overview"]["entry_point_count"] is None
    assert payload["overview"]["cpp_entry_point_count"] is None
    for detail in ("full", "summary"):
        markdown = MarkdownRenderer().render(report, detail=detail)
        assert "- Python 入口候选：未运行" in markdown
        assert "- C++ 入口候选：未运行" in markdown
        entries = markdown.split("## 入口候选", 1)[1].split("\n## ", 1)[0]
        assert entries.count("`not_run`") == 2
        assert "未识别到" not in entries


def test_language_failure_keeps_other_language_entry_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("python failed")

    monkeypatch.setattr(PythonAnalyzer, "analyze", fail)
    report = analyze_repository(FIXTURE)
    payload = json.loads(JsonRenderer().render(report))
    assert payload["overview"]["entry_point_count"] is None
    assert payload["overview"]["cpp_entry_point_count"] == 1
    assert payload["dependencies"]["status"] == "not_run"
    for detail in ("full", "summary"):
        markdown = MarkdownRenderer().render(report, detail=detail)
        entries = markdown.split("## 入口候选", 1)[1].split("\n## ", 1)[0]
        assert "`failed`" in entries
        assert "`completed`" in entries
        assert "src/main.cc" in entries
        assert "未识别到 Python" not in entries


def test_file_failure_does_not_report_an_empty_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise OSError("scan failed")

    monkeypatch.setattr(FileAnalyzer, "analyze", fail)
    report = analyze_repository(FIXTURE)
    payload = json.loads(JsonRenderer().render(report))
    for key in (
        "file_count",
        "non_empty_lines",
        "language_count",
        "comment_lines",
        "entry_point_count",
        "cpp_entry_point_count",
        "dependency_nodes",
        "dependency_edges",
        "cycle_count",
    ):
        assert payload["overview"][key] is None
    markdown = MarkdownRenderer().render(report)
    assert "- 文件数：失败" in markdown
    assert "- 非空行数：未运行" in markdown


@pytest.mark.parametrize("git_state", ["disabled", "failed", "unavailable"])
def test_missing_git_preserves_navigation_without_fabricating_scores(
    git_state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("git failed")

    options = AnalysisOptions(git_enabled=git_state != "disabled")
    if git_state == "failed":
        monkeypatch.setattr(GitAnalyzer, "analyze", fail)
    elif git_state == "unavailable":
        monkeypatch.setattr(
            GitProvider,
            "summary",
            lambda *args: GitSummary(error="history unavailable"),
        )
    report = analyze_repository(FIXTURE, options=options)
    assert report.analyzer_results["insights"].status == "completed"
    assert report.insights.reading_order
    assert report.insights.reading_paths
    assert not report.insights.change_attention
    for score in report.insights.module_scores:
        assert score.git_changes is None
        assert score.recent_changes is None
        assert score.git_score is None
        assert score.change_attention_score is None
        assert score.reading_priority_score == round(
            score.size_score + score.dependency_score + score.entry_score,
            2,
        )
    payload = json.loads(JsonRenderer().render(report))
    attention = payload["insights"]["change_attention_analysis"]
    assert attention["status"] == "not_run"
    assert "Git" in attention["reason"]
    for score in payload["insights"]["module_scores"]:
        assert score["git_changes"] is None
        assert score["recent_changes"] is None
        assert score["scores"]["git"] is None
        assert score["scores"]["change_attention_score"] is None
    for detail in ("full", "summary"):
        markdown = MarkdownRenderer().render(report, detail=detail)
        attention_section = markdown.split("## 变更关注模块", 1)[1].split("\n## ", 1)[0]
        assert "`not_run`" in attention_section
        assert attention["reason"] in attention_section
        assert "未检测到" not in attention_section
    assert "未计算" in MarkdownRenderer().render(report)


def test_available_git_with_zero_changes_is_a_completed_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GitProvider, "summary", lambda *args: GitSummary(available=True)
    )
    report = analyze_repository(FIXTURE)
    availability = report.change_attention_availability()
    assert availability.status == "completed"
    assert availability.reason is None
    assert not report.insights.change_attention
    for score in report.insights.module_scores:
        assert score.git_changes == score.recent_changes == score.git_score == 0
        assert score.change_attention_score == score.dependency_score


def test_missing_execution_records_remain_unknown() -> None:
    report = RepositoryReport(repository=Repository.from_path(FIXTURE))
    payload = json.loads(JsonRenderer().render(report))
    assert report.change_attention_availability().status == "not_run"
    assert payload["overview"]["file_count"] is None
    assert payload["python"]["reason"] == "没有执行记录"
    assert payload["insights"]["change_attention_analysis"]["status"] == "not_run"
