"""Streamlit UI 运行状态和预设测试。"""

from repopath.interface.ui.profiles import (
    PROFILE_SPECS,
    label_for_profile,
    profile_for_label,
)
from repopath.interface.ui.state import AnalysisSnapshot, UiRunState
from repopath.model.options import AnalysisOptions


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


def test_snapshot_marks_only_active_runtime_states_as_running() -> None:
    """验证快照仅将准备、运行和取消中视为活跃任务。"""
    active = [
        UiRunState.PENDING,
        UiRunState.RUNNING,
        UiRunState.CANCELLING,
    ]
    inactive = [
        UiRunState.IDLE,
        UiRunState.CANCELLED,
        UiRunState.FINISHED,
        UiRunState.ERROR,
    ]

    assert all(AnalysisSnapshot(state=item).active for item in active)
    assert not any(
        AnalysisSnapshot(state=item).active for item in inactive
    )
