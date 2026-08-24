"""Streamlit 会话运行状态。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, MutableMapping

from ...model.options import AnalysisOptions
from ...model.report import RepositoryReport
from ...model.result import AnalysisProgress


class UiRunState(StrEnum):
    """定义页面分析任务的生命周期状态。"""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


@dataclass(frozen=True)
class UiError:
    """保存可展示的错误类别、建议和原始信息。"""

    category: str
    summary: str
    suggestion: str
    details: str


@dataclass(frozen=True)
class AnalysisSnapshot:
    """保存一次页面分析的输入、进度、结果和错误。"""

    state: UiRunState = UiRunState.IDLE
    source: str = ""
    options: AnalysisOptions | None = None
    current_stage: str = ""
    progress_percent: int = 0
    report: RepositoryReport | None = None
    error: UiError | None = None
    elapsed_seconds: float | None = None


_STATE_KEY = "repopath.analysis_snapshot"


def get_snapshot(session_state: MutableMapping[str, Any]) -> AnalysisSnapshot:
    """从会话状态读取当前分析快照。"""
    snapshot = session_state.get(_STATE_KEY)
    return snapshot if isinstance(snapshot, AnalysisSnapshot) else AnalysisSnapshot()


def save_snapshot(session_state: MutableMapping[str, Any], snapshot: AnalysisSnapshot) -> None:
    """将分析快照写入会话状态。"""
    session_state[_STATE_KEY] = snapshot


def begin_run(session_state: MutableMapping[str, Any], source: str, options: AnalysisOptions) -> AnalysisSnapshot:
    """开始新分析并清理上一次报告和错误。"""
    snapshot = AnalysisSnapshot(state=UiRunState.RUNNING, source=source, options=options, current_stage="正在准备分析")
    save_snapshot(session_state, snapshot)
    return snapshot


def update_progress(session_state: MutableMapping[str, Any], event: AnalysisProgress) -> AnalysisSnapshot:
    """用 Pipeline 事件更新当前会话进度。"""
    snapshot = get_snapshot(session_state)
    updated = AnalysisSnapshot(
        state=UiRunState.RUNNING,
        source=snapshot.source,
        options=snapshot.options,
        current_stage=f"{event.analyzer}：{event.status}",
        progress_percent=event.percent,
    )
    save_snapshot(session_state, updated)
    return updated


def finish_run(session_state: MutableMapping[str, Any], report: RepositoryReport) -> AnalysisSnapshot:
    """保存成功报告并标记本次分析完成。"""
    snapshot = AnalysisSnapshot(
        state=UiRunState.FINISHED,
        source=str(report.repository.root),
        options=report.options,
        current_stage="分析完成",
        progress_percent=100,
        report=report,
        elapsed_seconds=report.elapsed_seconds,
    )
    save_snapshot(session_state, snapshot)
    return snapshot


def fail_run(session_state: MutableMapping[str, Any], exc: Exception) -> AnalysisSnapshot:
    """保存失败快照并确保不保留上一次报告。"""
    previous = get_snapshot(session_state)
    snapshot = AnalysisSnapshot(state=UiRunState.ERROR, source=previous.source, options=previous.options, current_stage="分析失败", error=classify_error(exc))
    save_snapshot(session_state, snapshot)
    return snapshot


def classify_error(exc: Exception) -> UiError:
    """将常见运行异常转为可执行的页面提示。"""
    if isinstance(exc, NotADirectoryError):
        return UiError("路径", "仓库目录不存在或不是目录。", "检查本地路径后重新分析。", str(exc))
    if isinstance(exc, PermissionError):
        return UiError("权限", "没有读取仓库所需的权限。", "为当前用户授予目录读取权限后重试。", str(exc))
    if isinstance(exc, ValueError):
        return UiError("配置", "分析配置无效。", "检查模式和高级配置中的数值。", str(exc))
    return UiError("分析", "分析过程未能完成。", "查看详细错误；可尝试快速模式确认仓库是否可读。", str(exc))
