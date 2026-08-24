"""Git 演进和热点统计测试。"""

from datetime import date, timedelta
import os
from pathlib import Path
import subprocess

from repopath.model.repository import Repository
from repopath.provider.git import GitProvider


def _git(
    root: Path, *args: str, commit_date: date | None = None
) -> None:
    """在测试仓库中执行一条 Git 命令。"""
    environment = os.environ.copy()
    if commit_date:
        timestamp = f"{commit_date.isoformat()}T12:00:00+0000"
        environment["GIT_AUTHOR_DATE"] = timestamp
        environment["GIT_COMMITTER_DATE"] = timestamp
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_git_summary_tracks_churn_periods_cochanges_and_authors(
    tmp_path: Path,
) -> None:
    """验证 Git 摘要可统计变更规模、活跃度和共同修改。"""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "RepoPath Test")
    _git(tmp_path, "config", "user.email", "repopath@example.com")
    source = tmp_path / "src"
    source.mkdir()
    old_date = date.today() - timedelta(days=120)
    recent_date = date.today() - timedelta(days=10)
    (source / "a.py").write_text("value = 1\n", encoding="utf-8")
    (source / "b.py").write_text("value = 2\n", encoding="utf-8")
    _git(tmp_path, "add", "src/a.py", "src/b.py")
    _git(tmp_path, "commit", "-m", "add sources", commit_date=old_date)
    (source / "a.py").write_text(
        "value = 1\nnext_value = 3\n", encoding="utf-8"
    )
    _git(tmp_path, "add", "src/a.py")
    _git(tmp_path, "commit", "-m", "update a", commit_date=recent_date)

    provider = GitProvider(Repository.from_path(tmp_path))
    summary = provider.summary()
    recent = provider.summary("30")

    assert summary.available is True
    assert summary.shallow is False
    assert summary.file_changes["src/a.py"].commits == 2
    assert summary.file_changes["src/a.py"].churn >= 2
    assert summary.file_changes["src/a.py"].added == 1
    assert summary.file_changes["src/a.py"].modified == 1
    assert summary.co_changes[("src/a.py", "src/b.py")] == 1
    assert summary.directory_authors["src"]["RepoPath Test"] == 3
    assert "src/a.py" in summary.active_paths
    assert "src/b.py" in summary.stable_paths
    assert recent.commit_count == 1
    assert set(recent.file_changes) == {"src/a.py"}
