"""Streamlit UI 运行状态和预设测试。"""

from pathlib import Path

from repopath.interface.ui.profiles import (
    PROFILE_SPECS,
    label_for_profile,
    profile_for_label,
)
from repopath.interface.ui.state import (
    UiRunState,
    begin_run,
    fail_run,
    finish_run,
    get_snapshot,
    update_progress,
)
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository
from repopath.model.result import (
    AnalyzerName,
    AnalysisProgress,
    AnalysisStatus,
)


def test_profile_specs_match_core_analyzer_matrix() -> None:
    """验证三个页面预设复用核心模式的 Analyzer 矩阵。"""
    assert [spec.label for spec in PROFILE_SPECS] == [
        "快速",
        "标准",
        "深度",
    ]
    assert profile_for_label(
        "快速"
    ).options() == AnalysisOptions.for_profile("fast")
    assert profile_for_label(
        "标准"
    ).options() == AnalysisOptions.for_profile("standard")
    assert profile_for_label(
        "深度"
    ).options() == AnalysisOptions.for_profile("deep")
    assert label_for_profile("custom") == "深度"


def test_snapshot_replaces_old_report_when_a_new_run_fails(
    tmp_path: Path,
) -> None:
    """验证重新分析失败后不会继续显示旧报告。"""
    state: dict[str, object] = {}
    options = AnalysisOptions.for_profile("deep")
    report = RepositoryReport(
        repository=Repository.from_path(tmp_path), options=options
    )

    finish_run(state, report)
    begin_run(state, str(tmp_path), options)
    running = update_progress(
        state,
        AnalysisProgress(
            AnalyzerName.FILES, 1, 3, 33, AnalysisStatus.RUNNING
        ),
    )
    failed = fail_run(state, NotADirectoryError("missing"))

    assert running.state is UiRunState.RUNNING
    assert running.progress_percent == 33
    assert failed.state is UiRunState.ERROR
    assert failed.report is None
    assert failed.error is not None
    assert failed.error.category == "路径"
    assert get_snapshot(state) == failed
