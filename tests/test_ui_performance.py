"""Streamlit 视图数据限量和报告缓存测试。"""

from typing import cast

from repopath.interface.ui.views import (
    _cached_report_text,
    _limited_sorted,
)
from repopath.model.report import RepositoryReport


class _StreamlitStub:
    """提供报告缓存所需的最小 Streamlit 接口。"""

    def __init__(self) -> None:
        """初始化空会话状态。"""
        self.session_state: dict[str, str] = {}


def test_limited_sorted_returns_the_same_top_n_order() -> None:
    """验证限量排序保留完整排序的前 N 项。"""
    values = list(range(10_000, -1, -1))

    result = _limited_sorted(values, 5, key=lambda item: item)

    assert result == [0, 1, 2, 3, 4]


def test_cached_report_text_renders_once_per_job() -> None:
    """验证相同任务编号不会重复生成报告文本。"""
    streamlit = _StreamlitStub()
    report = cast(RepositoryReport, object())
    calls = 0

    def render(_: RepositoryReport) -> str:
        """记录渲染次数并返回固定文本。"""
        nonlocal calls
        calls += 1
        return "报告文本"

    first = _cached_report_text(
        report, streamlit, "markdown", render, "job-1"
    )
    second = _cached_report_text(
        report, streamlit, "markdown", render, "job-1"
    )

    assert first == second == "报告文本"
    assert calls == 1


def test_cached_report_text_keeps_detail_formats_separate() -> None:
    """同一任务切换摘要、完整和 JSON 时不串内容，仅淘汰旧任务。"""
    streamlit = _StreamlitStub()
    report = cast(RepositoryReport, object())
    calls: list[str] = []

    def render_format(format_name: str, job: str = "job-1") -> str:
        def render(_: RepositoryReport) -> str:
            calls.append(format_name)
            return f"{job}:{format_name}"

        return _cached_report_text(report, streamlit, format_name, render, job)

    for _ in range(2):
        for format_name in ("markdown-summary", "markdown-full", "json"):
            assert render_format(format_name) == f"job-1:{format_name}"
    assert calls == ["markdown-summary", "markdown-full", "json"]
    assert render_format("markdown-summary", "job-2") == "job-2:markdown-summary"
    assert list(streamlit.session_state) == ["_repopath_report_job-2_markdown-summary"]
