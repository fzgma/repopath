"""C++ 基础静态分析器。"""

import re

from ...core.context import AnalysisContext
from ...model.cpp import CppAnalysis, CppEntryPoint, CppFileAnalysis
from ...model.language import Language
from ...model.result import AnalysisResult, AnalysisState, AnalyzerName
from ...model.source import SourceDependency, SourceSymbol
from ..base import Analyzer
from .includes import IncludeResolver, scan_source

TYPE_PATTERN = re.compile(
    r"^[ \t\f\v]*(?:class|struct)\s+([A-Za-z_]\w*)", re.MULTILINE
)
NAMESPACE_PATTERN = re.compile(
    r"^[ \t\f\v]*namespace\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)",
    re.MULTILINE,
)
FUNCTION_PATTERN = re.compile(
    r"^[ \t\f\v]*(?!if\b|for\b|while\b|switch\b|catch\b)"
    r"(?:[A-Za-z_~][\w:<>,~*&]*\s+)+"
    r"((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\([^;{}]*\)\s*"
    r"(?:const\s*)?(?:noexcept\s*)?(?P<ending>\{|;|:)",
    re.MULTILINE,
)


class CppAnalyzer(Analyzer):
    """直接读取 C++ 源码，识别 include、符号和入口候选。"""

    name = AnalyzerName.CPP

    def analyze(
        self, context: AnalysisContext, state: AnalysisState
    ) -> AnalysisResult:
        """从扫描范围内的文件构建阅读关系，不展开宏或执行编译。"""
        files = [
            file
            for file in state.artifacts.files
            if file.language in {Language.CPP, Language.CPP_HEADER}
        ]
        analysis = CppAnalysis()
        warnings: list[str] = []
        resolver = IncludeResolver(
            context.repository.root, [file.path for file in files]
        )

        for file in files:
            context.cancellation.raise_if_cancelled()
            source = context.filesystem.read_text(file.path)
            if source is None:
                warnings.append(
                    "无法读取 C++ 文件："
                    f"{context.repository.relative_path(file.path)}"
                )
                continue
            item = CppFileAnalysis(path=file.path)
            source_name = context.repository.relative_path(file.path)
            parsed = scan_source(source)
            item.include_details = parsed.includes
            item.includes = [include.name for include in parsed.includes]
            analysis.include_counts.update(item.includes)
            for match in FUNCTION_PATTERN.finditer(parsed.code):
                name = match.group(1)
                line, conditions = parsed.location(match.start(1))
                item.functions.append(
                    SourceSymbol(
                        name.split("::")[-1], "function", file.path, line
                    )
                )
                if (
                    name in {"main", "wmain", "WinMain", "wWinMain"}
                    and match.group("ending") == "{"
                ):
                    analysis.entry_points.append(
                        CppEntryPoint(
                            name, "function", file.path, line, conditions
                        )
                    )
            item.types = [
                SourceSymbol(
                    match.group(1),
                    "class_or_struct",
                    file.path,
                    parsed.location(match.start(1))[0],
                )
                for match in TYPE_PATTERN.finditer(parsed.code)
            ]
            item.namespaces = [
                SourceSymbol(
                    match.group(1),
                    "namespace",
                    file.path,
                    parsed.location(match.start(1))[0],
                )
                for match in NAMESPACE_PATTERN.finditer(parsed.code)
            ]
            analysis.files[file.path] = item

            for include in item.include_details:
                resolver.resolve(file.path, include)
                if include.target is not None:
                    analysis.dependencies.append(
                        SourceDependency(
                            source_name,
                            context.repository.relative_path(
                                include.target
                            ),
                            "include",
                        )
                    )
        state.artifacts.cpp = analysis
        return AnalysisResult(name=self.name, warnings=warnings)
