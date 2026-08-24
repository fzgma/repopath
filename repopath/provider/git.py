"""Git 命令 Provider。"""

import subprocess
from collections import Counter

from ..model.git import GitSummary
from ..model.repository import Repository


class GitProvider:
    """提供 Git 历史命令执行和结果解析能力。"""

    def __init__(self, repository: Repository) -> None:
        """创建绑定到指定仓库的 Git Provider。"""
        self.repository = repository

    def _run(self, *args: str) -> str:
        """执行 Git 命令并在失败时抛出异常。"""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repository.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"无法执行 Git：{exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Git 命令执行失败")
        return result.stdout.strip()

    def summary(self) -> GitSummary:
        """读取提交、作者、最近提交和高频修改路径统计。"""
        try:
            commit_count = int(self._run("rev-list", "--count", "HEAD"))
            author_rows = self._run("log", "--format=%an").splitlines()
            commit_rows = self._run(
                "log",
                "-n",
                "10",
                "--date=short",
                "--format=%h%x09%an%x09%ad%x09%s",
            ).splitlines()
            month_rows = self._run("log", "--date=format:%Y-%m", "--format=%ad").splitlines()
            first_commit_date = self._run("log", "--reverse", "-1", "--date=short", "--format=%ad")
            last_commit_date = self._run("log", "-1", "--date=short", "--format=%ad")
            changed_rows = self._run("log", "--format=", "--name-only").splitlines()
        except (RuntimeError, ValueError) as exc:
            return GitSummary(error=str(exc))

        recent_commits = []
        for row in commit_rows:
            fields = row.split("\t", 3)
            if len(fields) == 4:
                recent_commits.append(tuple(fields))
        return GitSummary(
            available=True,
            commit_count=commit_count,
            authors=Counter(author_rows),
            recent_commits=recent_commits,
            changed_paths=Counter(path for path in changed_rows if path.strip()),
            commits_by_month=Counter(month for month in month_rows if month.strip()),
            first_commit_date=first_commit_date or None,
            last_commit_date=last_commit_date or None,
        )
