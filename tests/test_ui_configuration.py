"""Streamlit UI 配置读取和任务提交测试。"""

from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

from repopath.core.config import (
    ensure_default_config,
    load_analysis_options,
)
from repopath.core.control import CancellationToken
from repopath.interface.ui.application import (
    _default_options,
    _fetch_rate_limit,
    _source_value_for_type,
    _start_analysis,
)
from repopath.interface.ui.runtime import AnalysisRuntime
from repopath.interface.ui.state import get_github_rate_limit
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import (
    GitHubRateLimit,
    Repository,
    RepositorySource,
    RepositorySourceType,
)
from repopath.model.result import AnalysisProgress


class _FakeStreamlit:
    """提供额度查询测试所需的最小 Streamlit 状态。"""

    def __init__(self) -> None:
        """初始化空会话状态。"""
        self.session_state: dict[str, object] = {}

    def error(self, message: str) -> None:
        """接受额度查询失败提示。"""

    def caption(self, message: str) -> None:
        """接受额度查询错误详情。"""


class _RecordingAnalyzer:
    """记录后台运行时收到的来源和配置。"""

    def __init__(self, report_root: Path) -> None:
        """保存生成最小报告时使用的仓库根目录。"""
        self.report_root = report_root
        self.sources: list[Path | RepositorySource] = []
        self.options: list[AnalysisOptions] = []

    def __call__(
        self,
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None = None,
        options: AnalysisOptions | None = None,
        progress_callback: Callable[[AnalysisProgress], None]
        | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> RepositoryReport:
        """记录调用并返回最小仓库报告。"""
        assert not isinstance(path, str)
        assert options is not None
        self.sources.append(path)
        self.options.append(options)
        return RepositoryReport(
            repository=Repository.from_path(self.report_root),
            source=(
                path
                if isinstance(path, RepositorySource)
                else RepositorySource.local(path)
            ),
            options=options,
        )


def _wait_for_runtime(runtime: AnalysisRuntime) -> None:
    """等待测试后台任务结束并在超时时失败。"""
    deadline = monotonic() + 2
    while runtime.snapshot().active and monotonic() < deadline:
        sleep(0.01)
    assert not runtime.snapshot().active


def test_ui_reads_report_settings_from_repository_config(
    tmp_path: Path,
) -> None:
    """验证 UI 默认值读取仓库配置中的报告设置。"""
    (tmp_path / ".repopath.toml").write_text(
        "[report]\nlimit = 12\nreading_limit = 4\n"
        "include_file_list = true\n[analyzers]\nreading = true\n",
        encoding="utf-8",
    )

    options = _default_options(str(tmp_path), load_analysis_options)

    assert options.result_limit == 12
    assert options.reading_limit == 4
    assert options.include_file_list is True
    assert options.reading_enabled is True


def test_ui_does_not_reuse_local_input_for_github_source() -> None:
    """验证本地报告不会将点号填入 GitHub 地址输入框。"""
    value = _source_value_for_type(
        ".", RepositorySourceType.LOCAL, is_github=True
    )

    assert value == ""


def test_ui_creates_config_and_submits_page_settings(
    tmp_path: Path,
) -> None:
    """验证 UI 创建配置并将页面设置提交给后台任务。"""
    analyzer = _RecordingAnalyzer(tmp_path)
    runtime = AnalysisRuntime(analyzer)

    _start_analysis(
        runtime=runtime,
        source=str(tmp_path),
        reference=None,
        is_github=False,
        label="深度",
        git_label="最近 30 天",
        max_file_size_mb=3,
        result_limit=20,
        reading_limit=6,
        include_file_list=True,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )
    _wait_for_runtime(runtime)

    assert (tmp_path / ".repopath.toml").exists()
    assert analyzer.options[0].git_period == "30"
    assert analyzer.options[0].max_file_size == 3 * 1024 * 1024
    assert analyzer.options[0].result_limit == 20
    assert analyzer.options[0].reading_limit == 6
    assert analyzer.options[0].include_file_list is True


def test_ui_submits_github_source_without_writing_config(
    tmp_path: Path,
) -> None:
    """验证 GitHub 来源按固定引用提交且不写远程配置。"""
    analyzer = _RecordingAnalyzer(tmp_path)
    runtime = AnalysisRuntime(analyzer)

    _start_analysis(
        runtime=runtime,
        source="example/demo",
        reference="main",
        is_github=True,
        label="快速",
        git_label="全部历史",
        max_file_size_mb=0,
        result_limit=10,
        reading_limit=10,
        include_file_list=False,
        reading_enabled=True,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )
    _wait_for_runtime(runtime)

    assert analyzer.sources == [
        RepositorySource.github("example/demo", "main")
    ]
    assert not (tmp_path / ".repopath.toml").exists()
    assert analyzer.options[0].reading_enabled is True


def test_ui_reading_switch_overrides_config_without_following_profile(
    tmp_path: Path,
) -> None:
    """验证指南配置可跨模式保留，也可显式关闭。"""
    (tmp_path / ".repopath.toml").write_text(
        "[analyzers]\nreading = true\n", encoding="utf-8"
    )
    analyzer = _RecordingAnalyzer(tmp_path)
    runtime = AnalysisRuntime(analyzer)
    for override in (None, False):
        _start_analysis(
            runtime=runtime,
            source=str(tmp_path),
            reference=None,
            is_github=False,
            label="快速",
            git_label="全部历史",
            max_file_size_mb=2,
            result_limit=50,
            reading_limit=10,
            include_file_list=False,
            reading_enabled=override,
            load_options=load_analysis_options,
            ensure_config=ensure_default_config,
        )
        _wait_for_runtime(runtime)

    assert [options.reading_enabled for options in analyzer.options] == [True, False]
    assert all(not options.dependencies_enabled for options in analyzer.options)


def test_ui_submits_github_snapshot_limits(
    tmp_path: Path,
) -> None:
    """验证 UI 高级配置会提交 GitHub 快照资源上限。"""
    analyzer = _RecordingAnalyzer(tmp_path)
    runtime = AnalysisRuntime(analyzer)

    _start_analysis(
        runtime=runtime,
        source="example/demo",
        reference=None,
        is_github=True,
        label="深度",
        git_label="全部历史",
        max_file_size_mb=0,
        result_limit=10,
        reading_limit=10,
        include_file_list=False,
        github_archive_max_mb=20,
        github_file_limit=2000,
        github_content_max_mb=30,
        github_file_max_mb=4,
        load_options=load_analysis_options,
        ensure_config=ensure_default_config,
    )
    _wait_for_runtime(runtime)

    options = analyzer.options[0]
    assert options.github_archive_max_bytes == 20 * 1024 * 1024
    assert options.github_file_limit == 2000
    assert options.github_content_max_bytes == 30 * 1024 * 1024
    assert options.github_file_max_bytes == 4 * 1024 * 1024


def test_ui_queries_rate_limit_only_while_runtime_is_idle(
    tmp_path: Path,
) -> None:
    """验证空闲运行时允许独立保存 GitHub 额度数据。"""
    streamlit = _FakeStreamlit()
    runtime = AnalysisRuntime(_RecordingAnalyzer(tmp_path))
    expected = GitHubRateLimit(60, 58, 1_787_580_330)

    _fetch_rate_limit(streamlit, lambda: expected, runtime)

    assert get_github_rate_limit(streamlit.session_state) == expected
