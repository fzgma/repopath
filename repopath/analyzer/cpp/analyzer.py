"""C++ 基础静态分析器。"""

import re
from pathlib import Path

from ...model.cpp import CppAnalysis, CppFileAnalysis
from ...model.language import Language
from ...model.result import AnalysisResult, AnalysisState
from ...model.source import SourceDependency, SourceSymbol
from ..base import Analyzer


INCLUDE_PATTERN = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.MULTILINE)
TYPE_PATTERN = re.compile(r'^\s*(?:class|struct)\s+([A-Za-z_]\w*)', re.MULTILINE)
NAMESPACE_PATTERN = re.compile(r'^\s*namespace\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)', re.MULTILINE)
FUNCTION_PATTERN = re.compile(
    r'^\s*(?!if\b|for\b|while\b|switch\b|catch\b)(?:[A-Za-z_~][\w:<>,~*&]*\s+)+((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:\{|;|:)',
    re.MULTILINE,
)


def line_number(source: str, offset: int) -> int:
    """将正则匹配位置转换为一开始的行号。"""
    return source.count("\n", 0, offset) + 1


class CppAnalyzer(Analyzer):
    """分析 C++ include、函数、类、结构体、命名空间和 main 入口。"""

    name = "cpp"

    def analyze(self, context, state: AnalysisState) -> AnalysisResult:
        """从 C++ 源文件和头文件中提取基础静态结构。"""
        files = [
            file
            for file in state.get_data("files", [])
            if file.language in {Language.CPP, Language.CPP_HEADER}
        ]
        analysis = CppAnalysis()
        warnings = []
        local_paths = {
            context.repository.relative_path(file.path): file.path
            for file in files
        }
        local_names = {file.path.name: file.path for file in files}

        for file in files:
            source = context.filesystem.read_text(file.path)
            if source is None:
                warnings.append(f"无法读取 C++ 文件：{context.repository.relative_path(file.path)}")
                continue
            item = CppFileAnalysis(path=file.path)
            source_name = context.repository.relative_path(file.path)
            item.includes = INCLUDE_PATTERN.findall(source)
            analysis.include_counts.update(item.includes)
            item.functions = [
                SourceSymbol(match.group(1).split("::")[-1], "function", file.path, line_number(source, match.start()))
                for match in FUNCTION_PATTERN.finditer(source)
            ]
            item.types = [
                SourceSymbol(match.group(1), "class_or_struct", file.path, line_number(source, match.start()))
                for match in TYPE_PATTERN.finditer(source)
            ]
            item.namespaces = [
                SourceSymbol(match.group(1), "namespace", file.path, line_number(source, match.start()))
                for match in NAMESPACE_PATTERN.finditer(source)
            ]
            analysis.entry_points.extend(symbol for symbol in item.functions if symbol.name == "main")
            analysis.files[file.path] = item

            for include in item.includes:
                target_path = local_paths.get(include) or local_names.get(Path(include).name)
                if target_path:
                    analysis.dependencies.append(
                        SourceDependency(source_name, context.repository.relative_path(target_path), "include")
                    )
        return AnalysisResult(name=self.name, data=analysis, warnings=warnings)
