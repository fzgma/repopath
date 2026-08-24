"""Streamlit 后台分析运行时测试。"""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from repopath.core.control import CancellationToken
from repopath.interface.ui.runtime import AnalysisRuntime
from repopath.interface.ui.state import UiRunState
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository, RepositorySource
from repopath.model.result import (
    AnalysisProgress,
    AnalysisStatus,
    AnalyzerName,
)


class _BlockingAnalyzer:
    """在测试事件释放前持续响应取消检查。"""

    def __init__(self, root: Path) -> None:
        """保存报告根目录并创建线程同步事件。"""
        self.root = root
        self.entered = Event()
        self.release = Event()
        self.calls = 0

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
        """发送进度并等待释放或取消。"""
        self.calls += 1
        self.entered.set()
        if progress_callback is not None:
            progress_callback(
                AnalysisProgress(
                    AnalyzerName.FILES,
                    1,
                    1,
                    25,
                    AnalysisStatus.RUNNING,
                )
            )
        while not self.release.wait(0.01):
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
        return RepositoryReport(
            repository=Repository.from_path(self.root),
            options=options or AnalysisOptions(),
        )


def _wait_for_state(
    runtime: AnalysisRuntime, expected: UiRunState
) -> None:
    """等待运行时进入指定状态并在超时时失败。"""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if runtime.snapshot().state is expected:
            return
        sleep(0.01)
    raise AssertionError(f"运行时未进入状态：{expected}")


def test_runtime_rejects_duplicate_start_and_finishes(
    tmp_path: Path,
) -> None:
    """验证活跃线程拒绝重复任务并保留最终报告。"""
    analyzer = _BlockingAnalyzer(tmp_path)
    runtime = AnalysisRuntime(analyzer)
    options = AnalysisOptions()

    assert runtime.start(
        source=str(tmp_path),
        analysis_source=tmp_path,
        options=options,
    )
    assert analyzer.entered.wait(1)
    assert not runtime.start(
        source=str(tmp_path),
        analysis_source=tmp_path,
        options=options,
    )
    assert runtime.snapshot().progress_percent == 25

    analyzer.release.set()
    _wait_for_state(runtime, UiRunState.FINISHED)

    assert analyzer.calls == 1
    assert runtime.snapshot().report is not None


def test_runtime_cancels_cooperatively_and_clears_report(
    tmp_path: Path,
) -> None:
    """验证停止请求经取消令牌结束任务且不保留报告。"""
    analyzer = _BlockingAnalyzer(tmp_path)
    runtime = AnalysisRuntime(analyzer)

    assert runtime.start(
        source=str(tmp_path),
        analysis_source=tmp_path,
        options=AnalysisOptions(),
    )
    assert analyzer.entered.wait(1)
    assert runtime.request_cancel()
    assert runtime.snapshot().state is UiRunState.CANCELLING

    _wait_for_state(runtime, UiRunState.CANCELLED)

    assert runtime.snapshot().report is None
    assert not runtime.request_cancel()
