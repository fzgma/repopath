"""Git 分析结果模型。"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class GitSummary:
    """保存仓库 Git 历史的基础统计。"""

    available: bool = False
    commit_count: int = 0
    authors: Counter[str] = field(default_factory=Counter)
    recent_commits: list[tuple[str, str, str, str]] = field(default_factory=list)
    changed_paths: Counter[str] = field(default_factory=Counter)
    commits_by_month: Counter[str] = field(default_factory=Counter)
    first_commit_date: str | None = None
    last_commit_date: str | None = None
    error: str | None = None
