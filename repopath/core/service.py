"""面向 CLI 和 UI 的统一分析服务。"""

from pathlib import Path

from ..model.report import RepositoryReport
from ..model.repository import Repository
from ..provider.filesystem import FileSystemProvider
from ..provider.git import GitProvider
from .composer import compose_report
from .context import AnalysisContext
from .pipeline import default_pipeline


def analyze_repository(path: str | Path, excluded_paths: set[Path] | None = None) -> RepositoryReport:
    """创建分析上下文并运行默认 Pipeline。"""
    repository = Repository.from_path(path)
    context = AnalysisContext(
        repository=repository,
        filesystem=FileSystemProvider(repository),
        git=GitProvider(repository),
        excluded_paths=excluded_paths or set(),
    )
    return compose_report(context, default_pipeline().run(context))
