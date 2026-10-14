"""C++ 静态分析结果模型。"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .source import SourceDependency, SourceSymbol


@dataclass(frozen=True)
class CppLocation:
    """记录仓库内语义事实的源码位置。"""

    path: Path
    line: int
    column: int


@dataclass
class CppSemanticSymbol:
    """按 Clang USR 合并跨翻译单元的声明与定义。"""

    usr: str
    name: str
    qualified_name: str
    kind: str
    type_spelling: str
    declarations: list[CppLocation] = field(default_factory=list)
    definitions: list[CppLocation] = field(default_factory=list)


@dataclass
class CppDirectCall:
    """记录已绑定到确定目标的直接调用及其翻译单元证据。"""

    caller_usr: str
    callee_usr: str
    location: CppLocation
    translation_units: list[Path] = field(default_factory=list)


@dataclass
class CppTranslationUnit:
    """记录编译数据库条目、解析参数和该翻译单元的覆盖状态。"""

    path: Path
    directory: Path
    arguments: tuple[str, ...] = ()
    status: str = "skipped"
    reason: str | None = None


@dataclass(frozen=True)
class CppDiagnostic:
    """保留编译器诊断，避免把有错误的翻译单元当作完整结果。"""

    severity: str
    message: str
    translation_unit: Path | None = None
    path: Path | None = None
    line: int = 0
    column: int = 0


@dataclass
class CppCoverage:
    """量化扫描范围内的文件覆盖与编译数据库解析情况。"""

    total_files: int = 0
    covered_files: int = 0
    total_translation_units: int = 0
    parsed_translation_units: int = 0
    failed_translation_units: int = 0
    uncovered_files: list[Path] = field(default_factory=list)


@dataclass
class CppFileAnalysis:
    """保存单个 C++ 文件的 include 和符号信息。"""

    path: Path
    includes: list[str] = field(default_factory=list[str])
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
    entry_points: list[SourceSymbol] = field(
        default_factory=list[SourceSymbol]
    )
    dependencies: list[SourceDependency] = field(
        default_factory=list[SourceDependency]
    )
    backend: str = "basic"
    analysis_level: str = "basic"
    semantic_status: str = "not_requested"
    semantic_reason: str | None = None
    compile_commands: Path | None = None
    library_version: str | None = None
    symbols: dict[str, CppSemanticSymbol] = field(default_factory=dict)
    calls: list[CppDirectCall] = field(default_factory=list)
    translation_units: list[CppTranslationUnit] = field(default_factory=list)
    diagnostics: list[CppDiagnostic] = field(default_factory=list)
    coverage: CppCoverage = field(default_factory=CppCoverage)

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
