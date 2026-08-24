"""Streamlit 会话运行状态。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, MutableMapping

from ...model.options import AnalysisOptions
from ...model.report import RepositoryReport
from ...model.repository import GitHubRateLimit


class UiRunState(StrEnum):
    """定义页面分析任务的生命周期状态。"""

    IDLE = "idle"
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
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

    job_id: str | None = None
    state: UiRunState = UiRunState.IDLE
    source: str = ""
    options: AnalysisOptions | None = None
    current_stage: str = ""
    progress_percent: int = 0
    report: RepositoryReport | None = None
    error: UiError | None = None
    elapsed_seconds: float | None = None

    @property
    def active(self) -> bool:
        """返回快照是否代表仍在执行或取消中的任务。"""
        return self.state in {
            UiRunState.PENDING,
            UiRunState.RUNNING,
            UiRunState.CANCELLING,
        }


_RATE_LIMIT_KEY = "repopath.github_rate_limit"


def get_github_rate_limit(
    session_state: MutableMapping[str, Any],
) -> GitHubRateLimit | None:
    """从会话状态读取最近一次 GitHub 额度查询结果。"""
    rate_limit = session_state.get(_RATE_LIMIT_KEY)
    return (
        rate_limit if isinstance(rate_limit, GitHubRateLimit) else None
    )


def save_github_rate_limit(
    session_state: MutableMapping[str, Any],
    rate_limit: GitHubRateLimit,
) -> None:
    """保存最近一次 GitHub 额度查询结果。"""
    session_state[_RATE_LIMIT_KEY] = rate_limit


def clear_github_rate_limit(
    session_state: MutableMapping[str, Any],
) -> None:
    """清除上一次 GitHub 额度查询结果。"""
    session_state.pop(_RATE_LIMIT_KEY, None)


def classify_error(exc: Exception) -> UiError:
    """将常见运行异常转为可执行的页面提示。"""
    if isinstance(exc, NotADirectoryError):
        return UiError(
            "路径",
            "仓库目录不存在或不是目录。",
            "检查本地路径后重新分析。",
            str(exc),
        )
    if isinstance(exc, PermissionError):
        return UiError(
            "权限",
            "没有读取仓库所需的权限。",
            "为当前用户授予目录读取权限后重试。",
            str(exc),
        )
    if isinstance(exc, ValueError):
        if "GitHub" in str(exc):
            return UiError(
                "来源",
                "GitHub 仓库地址或引用无效。",
                "检查仓库地址和分支、标签或提交 SHA 后重试。",
                str(exc),
            )
        return UiError(
            "配置",
            "分析配置无效。",
            "检查模式和高级配置中的数值。",
            str(exc),
        )
    return UiError(
        "分析",
        "分析过程未能完成。",
        "查看详细错误；可尝试快速模式确认仓库是否可读。",
        str(exc),
    )
