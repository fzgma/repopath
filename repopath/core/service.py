"""面向 CLI 和 UI 的统一分析服务。"""

from pathlib import Path
from collections.abc import Callable
from time import perf_counter

from ..model.options import AnalysisOptions
from ..model.report import RepositoryReport
from ..model.repository import (
    GitHubRateLimit,
    Repository,
    RepositorySource,
    RepositorySourceType,
)
from ..model.result import AnalysisProgress
from ..provider.filesystem import FileSystemProvider
from ..provider.git import GitProvider, UnavailableGitProvider
from ..provider.github import GitHubApiClient, GitHubSnapshot
from .composer import compose_report
from .context import AnalysisContext
from .pipeline import default_pipeline
from .config import load_analysis_options
from .control import CancellationToken


def fetch_github_rate_limit(
    github_client: GitHubApiClient | None = None,
) -> GitHubRateLimit:
    """读取当前 Token 或公网 IP 的 GitHub Core API 额度。"""
    return (github_client or GitHubApiClient()).rate_limit()


def analyze_repository(
    path: str | Path | RepositorySource,
    excluded_paths: set[Path] | None = None,
    options: AnalysisOptions | None = None,
    progress_callback: Callable[[AnalysisProgress], None] | None = None,
    *,
    github_client: GitHubApiClient | None = None,
    cancellation_token: CancellationToken | None = None,
) -> RepositoryReport:
    """根据本地或 GitHub 来源创建上下文并运行默认 Pipeline。"""
    source = (
        path
        if isinstance(path, RepositorySource)
        else RepositorySource.local(path)
    )
    if source.type is RepositorySourceType.GITHUB:
        return _analyze_github_snapshot(
            source,
            options,
            progress_callback,
            github_client,
            cancellation_token,
        )
    repository = Repository.from_source(source)
    resolved_options = options or load_analysis_options(repository.root)
    context = _build_context(
        repository,
        source,
        options=resolved_options,
        git=GitProvider(repository),
        excluded_paths=excluded_paths,
        cancellation_token=cancellation_token,
    )
    return _run_pipeline(context, progress_callback)


def _analyze_github_snapshot(
    source: RepositorySource,
    options: AnalysisOptions | None,
    progress_callback: Callable[[AnalysisProgress], None] | None,
    github_client: GitHubApiClient | None,
    cancellation_token: CancellationToken | None,
) -> RepositoryReport:
    """物化 GitHub 固定提交并复用本地静态分析 Pipeline。"""
    resolved_options = options or AnalysisOptions()
    cancellation = cancellation_token or CancellationToken()
    cancellation.raise_if_cancelled()
    with GitHubSnapshot(source, github_client) as snapshot:
        cancellation.raise_if_cancelled()
        context = _build_context(
            snapshot.repository,
            snapshot.resolved_source,
            options=resolved_options,
            git=UnavailableGitProvider(
                "GitHub 公开仓库快照不提供 Git 演进统计"
            ),
            excluded_paths=None,
            cancellation_token=cancellation,
        )
        report = _run_pipeline(context, progress_callback)
        report.github_rate_limit = snapshot.rate_limit
        return report


def _build_context(
    repository: Repository,
    source: RepositorySource,
    *,
    options: AnalysisOptions,
    git: GitProvider | UnavailableGitProvider,
    excluded_paths: set[Path] | None,
    cancellation_token: CancellationToken | None,
) -> AnalysisContext:
    """按统一文件和 Git Provider 构造分析上下文。"""
    options.validate()
    return AnalysisContext(
        repository=repository,
        source=source,
        filesystem=FileSystemProvider(
            repository,
            excluded_patterns=options.excluded_patterns,
            max_file_size=options.max_file_size,
            follow_symlinks=options.follow_symlinks,
        ),
        git=git,
        options=options,
        excluded_paths=excluded_paths or set(),
        cancellation=cancellation_token or CancellationToken(),
    )


def _run_pipeline(
    context: AnalysisContext,
    progress_callback: Callable[[AnalysisProgress], None] | None,
) -> RepositoryReport:
    """执行默认 Pipeline 并记录总耗时。"""
    started_at = perf_counter()
    report = compose_report(
        context,
        default_pipeline(context.options).run(
            context, progress_callback
        ),
    )
    report.elapsed_seconds = round(perf_counter() - started_at, 6)
    return report
