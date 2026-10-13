"""验证 Streamlit 展示真实执行状态和 Git 派生数据可用性。"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from repopath.analyzer.dependency_analyzer import DependencyAnalyzer
from repopath.analyzer.git_analyzer import GitAnalyzer
from repopath.analyzer.python import PythonAnalyzer
from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_repo"


def _render_status_report(report: object) -> None:
    """为 AppTest 提供独立且无需后台任务的实际报告页面。"""
    from typing import cast

    import streamlit as st

    from repopath.interface.ui.views import render_report
    from repopath.model.report import RepositoryReport

    render_report(cast(RepositoryReport, report), st)


def test_ui_disabled_analyzers_do_not_display_empty_results() -> None:
    report = analyze_repository(FIXTURE, options=AnalysisOptions.for_profile("fast"))
    app = AppTest.from_function(_render_status_report, args=(report,)).run()

    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["依赖"] == metrics["入口"] == "未运行"
    for view in ("Python", "C++", "Git", "依赖关系", "推荐阅读"):
        app.segmented_control[0].set_value(view).run()
        assert not app.exception
        messages = [item.value for item in app.info]
        assert any(
            "not_run" in message and "profile=fast" in message for message in messages
        )
        assert not any("当前没有" in message for message in messages)


def test_ui_standard_entries_do_not_depend_on_the_unified_graph() -> None:
    report = analyze_repository(
        FIXTURE, options=AnalysisOptions.for_profile("standard")
    )
    app = AppTest.from_function(_render_status_report, args=(report,)).run()
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["入口"] == "2"
    assert metrics["依赖"] == "未运行"


def test_ui_entry_metric_retains_completed_language_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("python failed")

    monkeypatch.setattr(PythonAnalyzer, "analyze", fail)
    report = analyze_repository(FIXTURE)
    app = AppTest.from_function(_render_status_report, args=(report,)).run()
    assert not app.exception
    entry_metric = next(item for item in app.metric if item.label == "入口")
    assert entry_metric.value == "1（部分）"
    assert "Python：失败" in entry_metric.proto.help
    assert "C++：已完成" in entry_metric.proto.help


def test_ui_dependency_failure_explains_why_reading_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("graph failed")

    monkeypatch.setattr(DependencyAnalyzer, "analyze", fail)
    report = analyze_repository(FIXTURE)
    app = AppTest.from_function(_render_status_report, args=(report,)).run()
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["依赖"] == "失败"
    app.segmented_control[0].set_value("依赖关系").run()
    assert not app.exception
    assert any("graph failed" in item.value for item in app.error)
    assert not any("没有可展示的依赖节点" in item.value for item in app.info)
    app.segmented_control[0].set_value("推荐阅读").run()
    assert not app.exception
    assert any("上游分析未完成：dependencies" in item.value for item in app.info)
    assert not any("没有符合筛选条件" in item.value for item in app.info)


def test_ui_missing_git_keeps_reading_and_marks_scores_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("git failed")

    monkeypatch.setattr(GitAnalyzer, "analyze", fail)
    report = analyze_repository(FIXTURE)
    app = AppTest.from_function(_render_status_report, args=(report,)).run()
    assert not app.exception
    assert any("变更关注分析状态：未运行" in item.value for item in app.info)
    app.segmented_control[0].set_value("推荐阅读").run()
    assert not app.exception
    assert app.dataframe
    scores = next(
        item.value for item in app.dataframe if "变更关注度" in item.value.columns
    )
    assert set(scores["Git"]) == {"未计算"}
    assert set(scores["变更关注度"]) == {"未计算"}
    assert any("变更关注度：未计算" in item.value for item in app.markdown)
    assert any("git failed" in item.value for item in app.info)
