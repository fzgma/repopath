"""面向 CLI 和 UI 的统一分析服务。"""

from pathlib import Path
from collections.abc import Callable
from time import perf_counter

from ..model.options import AnalysisOptions
from ..model.report import RepositoryReport
from ..model.repository import Repository, RepositorySource
from ..model.result import AnalysisProgress
from ..provider.filesystem import FileSystemProvider
from ..provider.git import GitProvider
from .composer import compose_report
from .context import AnalysisContext
from .pipeline import default_pipeline
from .config import load_analysis_options


def analyze_repository(
    path: str | Path | RepositorySource,
    excluded_paths: set[Path] | None = None,
    options: AnalysisOptions | None = None,
    progress_callback: Callable[[AnalysisProgress], None] | None = None,
) -> RepositoryReport:
    """创建分析上下文并运行默认 Pipeline。"""
    source = path if isinstance(path, RepositorySource) else RepositorySource.local(path)
    repository = Repository.from_source(source)
    resolved_options = options or load_analysis_options(repository.root)
    resolved_options.validate()
    context = AnalysisContext(
        repository=repository,
        source=source,
        filesystem=FileSystemProvider(
            repository,
            excluded_patterns=resolved_options.excluded_patterns,
            max_file_size=resolved_options.max_file_size,
            follow_symlinks=resolved_options.follow_symlinks,
        ),
        git=GitProvider(repository),
        options=resolved_options,
        excluded_paths=excluded_paths or set(),
    )
    started_at = perf_counter()
    report = compose_report(
        context,
        default_pipeline(resolved_options).run(context, progress_callback),
    )
    report.elapsed_seconds = round(perf_counter() - started_at, 6)
    return report
