"""Python AST 和模块关系分析器。"""

import ast
from pathlib import Path

from ...core.context import AnalysisContext
from ...model.language import Language
from ...model.python import EntryPoint, ModuleSummary, PythonAnalysis
from ...model.result import AnalysisResult, AnalysisState, AnalyzerName
from ...model.source import SourceDependency, SourceSymbol
from ..base import Analyzer


ENTRY_FILE_NAMES = {"main.py", "manage.py", "__main__.py"}


def module_name(path: Path, root: Path) -> str:
    """将 Python 文件路径转换为本地模块名称。"""
    relative = path.relative_to(root).with_suffix("")
    if relative.name == "__init__":
        relative = relative.parent
    return ".".join(relative.parts) or path.stem


def parse_tree(source: str) -> ast.Module | None:
    """解析 Python 源码并在语法错误时返回空值。"""
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def has_main_guard(tree: ast.Module) -> bool:
    """判断语法树是否包含主程序入口判断。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(
            node.test, ast.Compare
        ):
            continue
        if (
            not isinstance(node.test.left, ast.Name)
            or node.test.left.id != "__name__"
        ):
            continue
        if any(
            isinstance(value, ast.Constant)
            and value.value == "__main__"
            for value in node.test.comparators
        ):
            return True
    return False


def collect_symbols(tree: ast.Module, path: Path) -> list[SourceSymbol]:
    """提取 Python 中定义的函数和类。"""
    symbols: list[SourceSymbol] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                SourceSymbol(node.name, "function", path, node.lineno)
            )
        elif isinstance(node, ast.ClassDef):
            symbols.append(
                SourceSymbol(node.name, "class", path, node.lineno)
            )
    return sorted(symbols, key=lambda item: (item.line, item.name))


def collect_imports(tree: ast.Module, source_module: str) -> list[str]:
    """提取运行时绝对导入和可解析的相对导入模块名。"""
    imports: set[str] = set()
    package_parts = source_module.split(".")[:-1]
    for node in _RuntimeImportVisitor().collect(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imports.add(node.module)
                continue
            if node.level == 0:
                continue
            parent = package_parts[
                : max(0, len(package_parts) - node.level + 1)
            ]
            base = parent + (
                node.module.split(".") if node.module else []
            )
            if base:
                imports.add(".".join(base))
            if not node.module:
                imports.update(
                    ".".join(parent + [alias.name])
                    for alias in node.names
                )
    return sorted(imports)


class _RuntimeImportVisitor(ast.NodeVisitor):
    """遍历运行时可执行分支中的 Python import 语句。"""

    def __init__(self) -> None:
        """初始化 import 结果与 TYPE_CHECKING 名称集合。"""
        self.import_nodes: list[ast.Import | ast.ImportFrom] = []
        self.type_checking_names = {"TYPE_CHECKING"}
        self.typing_module_names = {"typing", "typing_extensions"}

    def collect(
        self, tree: ast.Module
    ) -> list[ast.Import | ast.ImportFrom]:
        """访问模块并返回仅来自运行时路径的导入节点。"""
        self.visit(tree)
        return self.import_nodes

    def visit_Import(self, node: ast.Import) -> None:
        """保存普通导入并记录 typing 模块别名。"""
        self.import_nodes.append(node)
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in self.typing_module_names:
                self.typing_module_names.add(alias.asname or root)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """保存 from 导入并记录 TYPE_CHECKING 别名。"""
        self.import_nodes.append(node)
        if node.module not in self.typing_module_names:
            return
        for alias in node.names:
            if alias.name == "TYPE_CHECKING":
                self.type_checking_names.add(alias.asname or alias.name)

    def visit_If(self, node: ast.If) -> None:
        """跳过 TYPE_CHECKING 分支并保留运行时 else 分支。"""
        if self._is_type_checking_guard(node.test):
            for statement in node.orelse:
                self.visit(statement)
            return
        self.generic_visit(node)

    def _is_type_checking_guard(self, test: ast.expr) -> bool:
        """判断条件是否为已识别的 TYPE_CHECKING 保护。"""
        if isinstance(test, ast.Name):
            return test.id in self.type_checking_names
        if not isinstance(test, ast.Attribute):
            return False
        return (
            test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id in self.typing_module_names
        )


class PythonAnalyzer(Analyzer):
    """分析 Python import、符号、入口和本地模块引用关系。"""

    name = AnalyzerName.PYTHON

    def analyze(
        self, context: AnalysisContext, state: AnalysisState
    ) -> AnalysisResult:
        """从已扫描的 Python 文件中提取静态结构信息。"""
        files = [
            file
            for file in state.artifacts.files
            if file.language == Language.PYTHON
        ]
        analysis = PythonAnalysis()
        warnings: list[str] = []
        local_modules = {
            module_name(file.path, context.repository.root): file
            for file in files
        }
        analysis.module_paths = {
            name: file.path for name, file in local_modules.items()
        }

        for file in files:
            context.cancellation.raise_if_cancelled()
            source = context.filesystem.read_text(file.path)
            if source is None:
                warnings.append(
                    "无法读取 Python 文件："
                    f"{context.repository.relative_path(file.path)}"
                )
                continue
            tree = parse_tree(source)
            if tree is None:
                warnings.append(
                    "Python 语法解析失败："
                    f"{context.repository.relative_path(file.path)}"
                )
                continue

            current_module = module_name(
                file.path, context.repository.root
            )
            imports = collect_imports(tree, current_module)
            analysis.imports_by_file[file.path] = imports
            analysis.import_counts.update(imports)
            analysis.symbols_by_file[file.path] = collect_symbols(
                tree, file.path
            )
            if file.path.name in ENTRY_FILE_NAMES:
                analysis.entry_points.append(
                    EntryPoint(file.path, "文件名约定")
                )
            elif has_main_guard(tree):
                analysis.entry_points.append(
                    EntryPoint(file.path, '包含 __name__ == "__main__"')
                )

        entry_modules = {
            module_name(entry.path, context.repository.root)
            for entry in analysis.entry_points
        }
        for path, imports in analysis.imports_by_file.items():
            context.cancellation.raise_if_cancelled()
            source_name = module_name(path, context.repository.root)
            for imported in imports:
                parts = imported.split(".")
                candidates = [
                    ".".join(parts[:index])
                    for index in range(len(parts), 0, -1)
                ]
                match = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate in local_modules
                    ),
                    None,
                )
                if match:
                    analysis.local_references[match] += 1
                    analysis.dependencies.append(
                        SourceDependency(source_name, match, "import")
                    )

        for name, file in local_modules.items():
            references = analysis.local_references[name]
            score = (
                file.non_empty_lines
                + references * 12
                + (20 if name in entry_modules else 0)
            )
            analysis.core_modules.append(
                ModuleSummary(
                    name, file.non_empty_lines, references, score
                )
            )
        analysis.core_modules.sort(
            key=lambda item: (item.score, item.name), reverse=True
        )
        state.artifacts.python = analysis
        return AnalysisResult(name=self.name, warnings=warnings)
