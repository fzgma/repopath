"""Git 分析结果模型。"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GitCommit:
    """记录最近一次提交的标识、作者、日期和摘要。"""

    identifier: str
    author: str
    date: str
    subject: str


@dataclass
class FileChangeStats:
    """保存单个文件在 Git 历史中的变更规模。"""

    commits: int = 0
    additions: int = 0
    deletions: int = 0
    added: int = 0
    deleted: int = 0
    modified: int = 0
    first_changed: str | None = None
    last_changed: str | None = None

    @property
    def churn(self) -> int:
        """返回文件累计增删行数。"""
        return self.additions + self.deletions


@dataclass
class MonthlyChangeStats:
    """保存单个月份的提交和代码增删统计。"""

    commits: int = 0
    additions: int = 0
    deletions: int = 0


@dataclass
class GitSummary:
    """保存仓库 Git 历史的基础统计。"""

    available: bool = False
    commit_count: int = 0
    authors: Counter[str] = field(default_factory=Counter[str])
    recent_commits: list[GitCommit] = field(
        default_factory=list[GitCommit]
    )
    changed_paths: Counter[str] = field(default_factory=Counter[str])
    commits_by_month: Counter[str] = field(default_factory=Counter[str])
    first_commit_date: str | None = None
    last_commit_date: str | None = None
    file_changes: dict[str, FileChangeStats] = field(
        default_factory=dict[str, FileChangeStats]
    )
    monthly_changes: dict[str, MonthlyChangeStats] = field(
        default_factory=dict[str, MonthlyChangeStats]
    )
    recent_30_days: Counter[str] = field(default_factory=Counter[str])
    recent_90_days: Counter[str] = field(default_factory=Counter[str])
    co_changes: Counter[tuple[str, str]] = field(
        default_factory=Counter[tuple[str, str]]
    )
    directory_authors: dict[str, Counter[str]] = field(
        default_factory=dict[str, Counter[str]]
    )
    active_paths: list[str] = field(default_factory=list[str])
    stable_paths: list[str] = field(default_factory=list[str])
    shallow: bool = False
    history_period: str = "all"
    error: str | None = None
