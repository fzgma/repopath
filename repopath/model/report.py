"""最终仓库报告模型。"""

from dataclasses import dataclass, field

from .file import FileRecord
from .git import GitSummary
from .python import PythonAnalysis
from .repository import Repository
from .statistics import RepositoryStats


@dataclass
class RepositoryReport:
    """组合所有分析器结果供 Renderer 和界面使用。"""

    repository: Repository
    files: list[FileRecord] = field(default_factory=list)
    stats: RepositoryStats = field(default_factory=RepositoryStats)
    python: PythonAnalysis = field(default_factory=PythonAnalysis)
    git: GitSummary = field(default_factory=GitSummary)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
