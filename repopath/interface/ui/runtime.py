"""Streamlit 分析任务的后台线程运行时。"""

from collections.abc import Callable, MutableMapping
from dataclasses import replace
from pathlib import Path
from threading import Lock, Thread
from time import perf_counter
from typing import Protocol, TypedDict, Unpack
from uuid import uuid4

from ...core.control import AnalysisCancelled, CancellationToken
from ...model.options import AnalysisOptions
from ...model.report import RepositoryReport
from ...model.repository import RepositorySource
from ...model.result import AnalysisProgress
from .state import AnalysisSnapshot, UiError, UiRunState, classify_error


class AnalyzeRepository(Protocol):
    """描述后台运行时调用的统一分析服务接口。"""

    def __call__(
        self,
        path: str | Path | RepositorySource,
        excluded_paths: set[Path] | None = None,
        options: AnalysisOptions | None = None,
        progress_callback: (
            Callable[[AnalysisProgress], None] | None
        ) = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> RepositoryReport:
        """执行一次可取消的仓库分析。"""
        ...


class _SnapshotChanges(TypedDict, total=False):
    """限定后台任务可以更新的快照字段及其类型。"""

    state: UiRunState
    current_stage: str
    progress_percent: int
    report: RepositoryReport | None
    error: UiError | None
    elapsed_seconds: float | None


class AnalysisRuntime:
    """在线程安全边界内管理单个会话的分析任务。"""

    def __init__(self, analyze: AnalyzeRepository) -> None:
        """保存分析服务并初始化空闲任务状态。"""
        self._analyze = analyze
        self._lock = Lock()
        self._thread: Thread | None = None
        self._token = CancellationToken()
        self._snapshot = AnalysisSnapshot()

    def snapshot(self) -> AnalysisSnapshot:
        """复制当前不可变快照供 UI 主线程渲染。"""
        with self._lock:
            return self._snapshot

    def start(
        self,
        *,
        source: str,
        analysis_source: Path | RepositorySource,
        options: AnalysisOptions,
    ) -> bool:
        """清理旧结果并启动一个新的后台分析任务。"""
        with self._lock:
            if self._is_thread_alive():
                return False
            job_id = uuid4().hex
            self._token = CancellationToken()
            self._snapshot = AnalysisSnapshot(
                job_id=job_id,
                state=UiRunState.PENDING,
                source=source,
                options=options,
                current_stage="正在准备分析",
            )
            self._thread = Thread(
                target=self._run,
                kwargs={
                    "job_id": job_id,
                    "analysis_source": analysis_source,
                    "options": options,
                    "token": self._token,
                },
                daemon=True,
                name=f"repopath-analysis-{job_id[:8]}",
            )
            thread = self._thread
        thread.start()
        return True

    def request_cancel(self) -> bool:
        """请求当前后台任务在下一个检查点停止。"""
        with self._lock:
            if not self._snapshot.active or not self._is_thread_alive():
                return False
            self._token.cancel()
            self._snapshot = self._replace_snapshot(
                state=UiRunState.CANCELLING,
                current_stage="正在停止分析",
            )
            return True

    def record_error(self, source: str, exc: Exception) -> None:
        """记录任务启动前的输入或配置错误并清理旧报告。"""
        with self._lock:
            if self._is_thread_alive():
                return
            self._snapshot = AnalysisSnapshot(
                state=UiRunState.ERROR,
                source=source,
                current_stage="分析失败",
                error=classify_error(exc),
            )

    def _run(
        self,
        *,
        job_id: str,
        analysis_source: Path | RepositorySource,
        options: AnalysisOptions,
        token: CancellationToken,
    ) -> None:
        """在工作线程中执行分析并提交最终快照。"""
        started_at = perf_counter()
        self._update_job(
            job_id,
            state=UiRunState.RUNNING,
            current_stage="正在准备分析",
        )
        try:
            report = self._analyze(
                analysis_source,
                None,
                options,
                lambda event: self._on_progress(job_id, event),
                cancellation_token=token,
            )
            token.raise_if_cancelled()
        except AnalysisCancelled:
            self._update_job(
                job_id,
                state=UiRunState.CANCELLED,
                current_stage="分析已停止",
                progress_percent=0,
                report=None,
                error=None,
                elapsed_seconds=perf_counter() - started_at,
            )
        except Exception as exc:
            self._update_job(
                job_id,
                state=UiRunState.ERROR,
                current_stage="分析失败",
                report=None,
                error=classify_error(exc),
                elapsed_seconds=perf_counter() - started_at,
            )
        else:
            self._update_job(
                job_id,
                state=UiRunState.FINISHED,
                current_stage="分析完成",
                progress_percent=100,
                report=report,
                error=None,
                elapsed_seconds=report.elapsed_seconds,
            )

    def _on_progress(
        self, job_id: str, event: AnalysisProgress
    ) -> None:
        """将工作线程的阶段事件写入当前任务快照。"""
        with self._lock:
            if self._snapshot.job_id != job_id:
                return
            state = (
                UiRunState.CANCELLING
                if self._token.cancelled
                else UiRunState.RUNNING
            )
            self._snapshot = self._replace_snapshot(
                state=state,
                current_stage=f"{event.analyzer}：{event.status}",
                progress_percent=event.percent,
            )

    def _update_job(
        self, job_id: str, **changes: Unpack[_SnapshotChanges]
    ) -> None:
        """仅在任务编号仍匹配时原子更新运行快照。"""
        with self._lock:
            if self._snapshot.job_id == job_id:
                self._snapshot = self._replace_snapshot(**changes)

    def _replace_snapshot(
        self, **changes: Unpack[_SnapshotChanges]
    ) -> AnalysisSnapshot:
        """以当前快照为基础创建字段更新后的新快照。"""
        return replace(self._snapshot, **changes)

    def _is_thread_alive(self) -> bool:
        """返回当前工作线程是否仍然存活。"""
        return self._thread is not None and self._thread.is_alive()


_RUNTIME_KEY = "repopath.analysis_runtime"


def get_analysis_runtime(
    session_state: MutableMapping[str, object],
    analyze: AnalyzeRepository,
) -> AnalysisRuntime:
    """获取当前 Streamlit 会话独享的分析运行时。"""
    runtime = session_state.get(_RUNTIME_KEY)
    if not isinstance(runtime, AnalysisRuntime):
        runtime = AnalysisRuntime(analyze)
        session_state[_RUNTIME_KEY] = runtime
    return runtime
