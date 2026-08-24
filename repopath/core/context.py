"""分析上下文模型。"""

from dataclasses import dataclass, field
from pathlib import Path

from ..model.repository import Repository
from ..provider.filesystem import FileSystemProvider
from ..provider.git import GitProvider


@dataclass
class AnalysisContext:
    """为所有 Analyzer 提供仓库、Provider 和输出排除路径。"""

    repository: Repository
    filesystem: FileSystemProvider
    git: GitProvider
    excluded_paths: set[Path] = field(default_factory=set)
