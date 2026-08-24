"""Python 静态分析结果模型。"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EntryPoint:
    """表示一个可能的 Python 程序入口。"""

    path: Path
    reason: str


@dataclass(frozen=True)
class ModuleSummary:
    """表示一个按规模和引用关系排序的模块候选。"""

    name: str
    lines: int
    references: int


@dataclass(frozen=True)
class DependencyEdge:
    """表示一个 Python 模块对另一个本地模块的依赖。"""

    source: str
    target: str


@dataclass
class PythonAnalysis:
    """保存 Python import、入口和本地模块引用分析结果。"""

    imports_by_file: dict[Path, list[str]] = field(default_factory=dict)
    import_counts: Counter[str] = field(default_factory=Counter)
    entry_points: list[EntryPoint] = field(default_factory=list)
    local_references: Counter[str] = field(default_factory=Counter)
    core_modules: list[ModuleSummary] = field(default_factory=list)
    dependencies: list[DependencyEdge] = field(default_factory=list)
