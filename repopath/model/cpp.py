"""C++ 静态分析结果模型。"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .source import SourceDependency, SourceSymbol


@dataclass
class CppInclude:
    """保留源码中的 include、条件和仓库内路径匹配结果。"""

    name: str
    line: int
    kind: str
    conditions: tuple[str, ...] = ()
    resolution: str = "unresolved"
    target: Path | None = None
    candidates: list[Path] = field(default_factory=list[Path])


@dataclass(frozen=True)
class CppEntryPoint(SourceSymbol):
    """记录入口候选及其所在的条件分支，不判断构建时是否启用。"""

    conditions: tuple[str, ...] = ()


@dataclass
class CppFileAnalysis:
    """保存单个 C++ 文件的 include 和符号信息。"""

    path: Path
    includes: list[str] = field(default_factory=list[str])
    include_details: list[CppInclude] = field(default_factory=list[CppInclude])
    functions: list[SourceSymbol] = field(
        default_factory=list[SourceSymbol]
    )
    types: list[SourceSymbol] = field(
        default_factory=list[SourceSymbol]
    )
    namespaces: list[SourceSymbol] = field(
        default_factory=list[SourceSymbol]
    )


@dataclass
class CppAnalysis:
    """保存 C++ include、符号、入口和本地依赖分析结果。"""

    files: dict[Path, CppFileAnalysis] = field(
        default_factory=dict[Path, CppFileAnalysis]
    )
    include_counts: Counter[str] = field(default_factory=Counter[str])
    entry_points: list[CppEntryPoint] = field(
        default_factory=list[CppEntryPoint]
    )
    dependencies: list[SourceDependency] = field(
        default_factory=list[SourceDependency]
    )

    @property
    def function_count(self) -> int:
        """返回已识别的函数数量。"""
        return sum(len(item.functions) for item in self.files.values())

    @property
    def type_count(self) -> int:
        """返回已识别的类和结构体数量。"""
        return sum(len(item.types) for item in self.files.values())

    @property
    def namespace_count(self) -> int:
        """返回已识别的命名空间数量。"""
        return sum(len(item.namespaces) for item in self.files.values())
