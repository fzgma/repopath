"""分析上下文模型。"""

from dataclasses import dataclass, field
from pathlib import Path

from ..model.options import AnalysisOptions
from ..model.repository import Repository, RepositorySource
from ..provider.base import (
    RepositoryFileProvider,
    RepositoryGitProvider,
)


@dataclass
class AnalysisContext:
    """为所有 Analyzer 提供仓库、Provider 和输出排除路径。"""

    repository: Repository
    source: RepositorySource
    filesystem: RepositoryFileProvider
    git: RepositoryGitProvider
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    excluded_paths: set[Path] = field(default_factory=set[Path])
