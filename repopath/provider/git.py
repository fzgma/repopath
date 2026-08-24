"""Git 命令 Provider。"""

import subprocess
from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import combinations

from ..model.git import FileChangeStats, GitCommit, GitSummary, MonthlyChangeStats
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

    def summary(self, period: str = "all") -> GitSummary:
        """读取提交历史并聚合文件、月份、作者和共同修改统计。"""
        log_args = [
            "log",
            "--date=short",
            "--format=@@@%H%x09%ad%x09%an",
            "--numstat",
        ]
        if period != "all":
            log_args.insert(1, f"--since={period}.days.ago")
        try:
            history_rows = self._run(*log_args).splitlines()
            status_args = ["log", "--format=", "--name-status"]
            if period != "all":
                status_args.insert(1, f"--since={period}.days.ago")
            status_rows = self._run(*status_args).splitlines()
            shallow = self._run("rev-parse", "--is-shallow-repository") == "true"
            recent_args = [
                "log",
                "-n",
                "10",
                "--date=short",
                "--format=%h%x09%an%x09%ad%x09%s",
            ]
            if period != "all":
                recent_args.insert(1, f"--since={period}.days.ago")
            commit_rows = self._run(*recent_args).splitlines()
        except RuntimeError as exc:
            return GitSummary(error=str(exc))

        recent_commits: list[GitCommit] = []
        for row in commit_rows:
            fields = row.split("\t", 3)
            if len(fields) == 4:
                recent_commits.append(GitCommit(fields[0], fields[1], fields[2], fields[3]))

        commits = _parse_numstat_history(history_rows)
        authors: Counter[str] = Counter[str]()
        changed_paths: Counter[str] = Counter[str]()
        commits_by_month: Counter[str] = Counter[str]()
        file_changes: dict[str, FileChangeStats] = {}
        monthly_changes: dict[str, MonthlyChangeStats] = {}
        recent_30_days: Counter[str] = Counter[str]()
        recent_90_days: Counter[str] = Counter[str]()
        co_changes: Counter[tuple[str, str]] = Counter[tuple[str, str]]()
        directory_authors: defaultdict[str, Counter[str]] = defaultdict(Counter[str])
        today = date.today()

        for commit_date, author, files in commits:
            authors[author] += 1
            month = commit_date[:7]
            commits_by_month[month] += 1
            monthly = monthly_changes.setdefault(month, MonthlyChangeStats())
            monthly.commits += 1
            parsed_date = date.fromisoformat(commit_date)
            unique_paths = sorted({path for _, _, path in files})
            for left, right in combinations(unique_paths[:50], 2):
                co_changes[(left, right)] += 1
            for additions, deletions, path in files:
                changed_paths[path] += 1
                stats = file_changes.setdefault(path, FileChangeStats())
                stats.commits += 1
                stats.additions += additions
                stats.deletions += deletions
                stats.first_changed = min(stats.first_changed or commit_date, commit_date)
                stats.last_changed = max(stats.last_changed or commit_date, commit_date)
                monthly.additions += additions
                monthly.deletions += deletions
                directory = path.split("/", 1)[0] if "/" in path else "."
                directory_authors[directory][author] += 1
                age = today - parsed_date
                if age <= timedelta(days=30):
                    recent_30_days[path] += 1
                if age <= timedelta(days=90):
                    recent_90_days[path] += 1

        dates = [commit_date for commit_date, _, _ in commits]
        for status, path in _parse_name_status(status_rows):
            stats = file_changes.setdefault(path, FileChangeStats())
            if status == "A":
                stats.added += 1
            elif status == "D":
                stats.deleted += 1
            else:
                stats.modified += 1
        active_paths = [path for path, _ in recent_90_days.most_common()]
        stable_paths = [
            path
            for path, _ in sorted(
                file_changes.items(),
                key=lambda item: (-item[1].commits, -item[1].churn, item[0]),
            )
            if path not in recent_90_days
        ]
        return GitSummary(
            available=True,
            commit_count=len(commits),
            authors=authors,
            recent_commits=recent_commits,
            changed_paths=changed_paths,
            commits_by_month=commits_by_month,
            first_commit_date=min(dates) if dates else None,
            last_commit_date=max(dates) if dates else None,
            file_changes=file_changes,
            monthly_changes=monthly_changes,
            recent_30_days=recent_30_days,
            recent_90_days=recent_90_days,
            co_changes=co_changes,
            directory_authors=dict(directory_authors),
            active_paths=active_paths,
            stable_paths=stable_paths,
            shallow=shallow,
            history_period=period,
        )


def _parse_numstat_history(
    rows: list[str],
) -> list[tuple[str, str, list[tuple[int, int, str]]]]:
    """解析带提交头的 Git numstat 输出。"""
    commits: list[tuple[str, str, list[tuple[int, int, str]]]] = []
    current_date = ""
    current_author = ""
    current_files: list[tuple[int, int, str]] = []
    for row in rows:
        if row.startswith("@@@"):
            if current_date:
                commits.append((current_date, current_author, current_files))
            fields = row[3:].split("\t", 2)
            current_date = fields[1] if len(fields) > 1 else ""
            current_author = fields[2] if len(fields) > 2 else "未知"
            current_files = []
            continue
        fields = row.split("\t", 2)
        if len(fields) != 3 or not current_date:
            continue
        additions = int(fields[0]) if fields[0].isdigit() else 0
        deletions = int(fields[1]) if fields[1].isdigit() else 0
        current_files.append((additions, deletions, fields[2]))
    if current_date:
        commits.append((current_date, current_author, current_files))
    return commits


def _parse_name_status(rows: list[str]) -> list[tuple[str, str]]:
    """解析 Git name-status 输出中的文件状态。"""
    changes: list[tuple[str, str]] = []
    for row in rows:
        fields = row.split("\t")
        if len(fields) < 2:
            continue
        status = fields[0][:1]
        path = fields[-1]
        if status in {"A", "D", "M", "R", "C", "T"} and path:
            changes.append((status, path))
    return changes
