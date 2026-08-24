"""Streamlit UI 配置读取和设置测试。"""

from collections.abc import Callable
from pathlib import Path

import pytest

from repopath.core.config import (
    ensure_default_config,
    load_analysis_options,
)
from repopath.interface.ui import application
from repopath.interface.ui.application import (
    _default_options,
    _fetch_rate_limit,
    _run_analysis,
    _source_value_for_type,
)
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import (
    GitHubRateLimit,
    Repository,
    RepositorySource,
    RepositorySourceType,
)
from repopath.model.result import AnalysisProgress
from repopath.interface.ui.state import (
    UiRunState,
    begin_run,
    get_github_rate_limit,
    get_snapshot,
)


class _FakeProgress:
    """记录 UI 进度条的最小替身。"""

    def progress(self, percent: int, text: str) -> None:
        """接受页面进度更新。"""

    def empty(self) -> None:
        """接受页面清理请求。"""


class _FakeStreamlit:
    """提供运行分析函数所需的最小 Streamlit 状态。"""

    def __init__(self) -> None:
        """初始化会话状态和进度条替身。"""
        self.session_state: dict[str, object] = {}

    def progress(self, percent: int, text: str) -> _FakeProgress:
        """返回可记录进度的替身对象。"""
        return _FakeProgress()

    def error(self, message: str) -> None:
        """接受额度查询失败提示。"""

    def caption(self, message: str) -> None:
        """接受额度查询错误详情。"""


def test_ui_reads_report_settings_from_repository_config(
    tmp_path: Path,
) -> None:
    """验证 UI 默认值读取仓库配置中的报告设置。"""
    (tmp_path / ".repopath.toml").write_text(
        "[report]\nlimit = 12\nreading_limit = 4\n"
        "include_file_list = true\n",
        encoding="utf-8",
    )

    options = _default_options(str(tmp_path), load_analysis_options)

    assert options.result_limit == 12
    assert options.reading_limit == 4
    assert options.include_file_list is True


def test_ui_does_not_reuse_local_input_for_github_source() -> None:
    """验证本地报告不会将点号填入 GitHub 地址输入框。"""
    assert (
        _source_value_for_type(
            ".", RepositorySourceType.LOCAL, is_github=True
        )
        == ""
    )


def test_ui_creates_config_and_applies_page_settings(
    tmp_path: Path,
) -> None:
    """验证 UI 分析前创建配置并以页面设置覆盖报告选项。"""
    streamlit = _FakeStreamlit()
    received: list[AnalysisOptions] = []

    def analyze(
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None,
        options: AnalysisOptions | None,
        progress_callback: Callable[[AnalysisProgress], None] | None,
    ) -> RepositoryReport:
        """记录 UI 传入选项并返回最小报告。"""
        assert isinstance(path, Path)
        assert options is not None
        received.append(options)
        return RepositoryReport(
            repository=Repository.from_path(path), options=options
        )

    _run_analysis(
        st=streamlit,
        source=str(tmp_path),
        reference=None,
        is_github=False,
        label="深度",
        git_label="最近 30 天",
        max_file_size_mb=3,
        result_limit=20,
        reading_limit=6,
        include_file_list=True,
        analyze=analyze,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )

    assert (tmp_path / ".repopath.toml").exists()
    assert received[0].git_period == "30"
    assert received[0].max_file_size == 3 * 1024 * 1024
    assert received[0].result_limit == 20
    assert received[0].reading_limit == 6
    assert received[0].include_file_list is True


def test_ui_uses_default_settings_for_github_source(
    tmp_path: Path,
) -> None:
    """验证 GitHub 分析将 URL 和引用传入 Core 而不写远程配置。"""
    streamlit = _FakeStreamlit()
    received: list[RepositorySource] = []

    def analyze(
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None,
        options: AnalysisOptions | None,
        progress_callback: Callable[[AnalysisProgress], None] | None,
    ) -> RepositoryReport:
        """记录远程来源并返回最小报告。"""
        assert isinstance(path, RepositorySource)
        assert options is not None
        received.append(path)
        return RepositoryReport(
            repository=Repository.from_path(tmp_path),
            source=path,
            options=options,
        )

    _run_analysis(
        st=streamlit,
        source="https://github.com/example/demo",
        reference="main",
        is_github=True,
        label="快速",
        git_label="全部历史",
        max_file_size_mb=0,
        result_limit=10,
        reading_limit=10,
        include_file_list=False,
        analyze=analyze,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )

    assert received == [
        RepositorySource.github(
            "https://github.com/example/demo", "main"
        )
    ]
    assert not (tmp_path / ".repopath.toml").exists()


def test_ui_ignores_second_analysis_while_a_run_is_active(
    tmp_path: Path,
) -> None:
    """验证运行中的页面不会再次启动同步分析。"""
    streamlit = _FakeStreamlit()
    begin_run(streamlit.session_state, str(tmp_path), AnalysisOptions())
    calls: list[Path] = []

    def analyze(
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None,
        options: AnalysisOptions | None,
        progress_callback: Callable[[AnalysisProgress], None] | None,
    ) -> RepositoryReport:
        """记录意外启动的分析调用。"""
        assert isinstance(path, Path)
        calls.append(path)
        return RepositoryReport(
            repository=Repository.from_path(path),
            options=options or AnalysisOptions(),
        )

    _run_analysis(
        st=streamlit,
        source=str(tmp_path),
        reference=None,
        is_github=False,
        label="快速",
        git_label="全部历史",
        max_file_size_mb=0,
        result_limit=10,
        reading_limit=10,
        include_file_list=False,
        analyze=analyze,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )

    assert calls == []
    assert (
        get_snapshot(streamlit.session_state).state
        is UiRunState.RUNNING
    )


def test_ui_ignores_queued_analysis_after_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证刚完成任务后到达的重复提交不会再次执行。"""
    streamlit = _FakeStreamlit()
    calls: list[Path] = []
    monkeypatch.setattr(application, "monotonic", lambda: 100.0)
    streamlit.session_state[
        application._LAST_ANALYSIS_COMPLETED_AT_KEY
    ] = 99.5

    def analyze(
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None,
        options: AnalysisOptions | None,
        progress_callback: Callable[[AnalysisProgress], None] | None,
    ) -> RepositoryReport:
        """记录意外启动的分析调用。"""
        assert isinstance(path, Path)
        calls.append(path)
        return RepositoryReport(
            repository=Repository.from_path(path),
            options=options or AnalysisOptions(),
        )

    _run_analysis(
        st=streamlit,
        source=str(tmp_path),
        reference=None,
        is_github=False,
        label="快速",
        git_label="全部历史",
        max_file_size_mb=0,
        result_limit=10,
        reading_limit=10,
        include_file_list=False,
        analyze=analyze,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )

    assert calls == []


def test_ui_queries_rate_limit_without_starting_analysis() -> None:
    """验证额度查询仅保存额度数据而不创建分析任务。"""
    streamlit = _FakeStreamlit()
    expected = GitHubRateLimit(60, 58, 1_787_580_330)

    _fetch_rate_limit(streamlit, lambda: expected)

    assert get_github_rate_limit(streamlit.session_state) == expected
    assert (
        get_snapshot(streamlit.session_state).state is UiRunState.IDLE
    )


def test_ui_ignores_rate_limit_query_while_analysis_is_running() -> (
    None
):
    """验证运行中不会执行额度查询。"""
    streamlit = _FakeStreamlit()
    begin_run(
        streamlit.session_state, "example/demo", AnalysisOptions()
    )
    calls: list[None] = []

    def fetch_rate_limit() -> GitHubRateLimit:
        """记录意外执行的额度查询。"""
        calls.append(None)
        return GitHubRateLimit(60, 58, 1_787_580_330)

    _fetch_rate_limit(streamlit, fetch_rate_limit)

    assert calls == []
