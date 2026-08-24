"""Python 静态分析结果模型。"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .source import SourceDependency, SourceSymbol


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
    score: int = 0


@dataclass
class PythonAnalysis:
    """保存 Python import、入口和本地模块引用分析结果。"""

    imports_by_file: dict[Path, list[str]] = field(default_factory=dict[Path, list[str]])
    import_counts: Counter[str] = field(default_factory=Counter[str])
    entry_points: list[EntryPoint] = field(default_factory=list[EntryPoint])
    local_references: Counter[str] = field(default_factory=Counter[str])
    core_modules: list[ModuleSummary] = field(default_factory=list[ModuleSummary])
    dependencies: list[SourceDependency] = field(default_factory=list[SourceDependency])
    symbols_by_file: dict[Path, list[SourceSymbol]] = field(default_factory=dict[Path, list[SourceSymbol]])
    module_paths: dict[str, Path] = field(default_factory=dict[str, Path])

    @property
    def function_count(self) -> int:
        """返回已识别的 Python 函数数量。"""
        return sum(sum(symbol.kind == "function" for symbol in symbols) for symbols in self.symbols_by_file.values())

    @property
    def class_count(self) -> int:
        """返回已识别的 Python 类数量。"""
        return sum(sum(symbol.kind == "class" for symbol in symbols) for symbols in self.symbols_by_file.values())
