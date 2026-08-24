"""Streamlit UI 配置读取和设置测试。"""

from collections.abc import Callable
from pathlib import Path

from repopath.core.config import ensure_default_config, load_analysis_options
from repopath.interface.ui.application import _default_options, _run_analysis
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository
from repopath.model.result import AnalysisProgress


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


def test_ui_reads_report_settings_from_repository_config(tmp_path: Path) -> None:
    """验证 UI 默认值读取仓库配置中的报告设置。"""
    (tmp_path / ".repopath.toml").write_text(
        "[report]\nlimit = 12\nreading_limit = 4\ninclude_file_list = true\n",
        encoding="utf-8",
    )

    options = _default_options(str(tmp_path), load_analysis_options)

    assert options.result_limit == 12
    assert options.reading_limit == 4
    assert options.include_file_list is True


def test_ui_creates_config_and_applies_page_settings(tmp_path: Path) -> None:
    """验证 UI 分析前创建配置并以页面设置覆盖报告选项。"""
    streamlit = _FakeStreamlit()
    received: list[AnalysisOptions] = []

    def analyze(
        path: Path,
        excluded_paths: set[Path] | None,
        options: AnalysisOptions | None,
        progress_callback: Callable[[AnalysisProgress], None] | None,
    ) -> RepositoryReport:
        """记录 UI 传入选项并返回最小报告。"""
        assert options is not None
        received.append(options)
        return RepositoryReport(repository=Repository.from_path(path), options=options)

    _run_analysis(
        streamlit,
        str(tmp_path),
        "深度",
        "最近 30 天",
        3,
        20,
        6,
        True,
        analyze,
        load_analysis_options,
        ensure_default_config,
    )

    assert (tmp_path / ".repopath.toml").exists()
    assert received[0].git_period == "30"
    assert received[0].max_file_size == 3 * 1024 * 1024
    assert received[0].result_limit == 20
    assert received[0].reading_limit == 6
    assert received[0].include_file_list is True
