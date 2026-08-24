"""Python AST 和模块关系分析器。"""

import ast
from ..model.language import Language
from ..model.python import DependencyEdge, EntryPoint, ModuleSummary, PythonAnalysis
from ..model.result import AnalysisResult, AnalysisState
from .base import Analyzer


ENTRY_FILE_NAMES = {"main.py", "app.py", "cli.py", "manage.py", "__main__.py"}


def parse_imports(source: str) -> list[str]:
    """解析 Python 源码并提取导入的模块名。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return sorted(imports)


def has_main_guard(source: str) -> bool:
    """判断 Python 源码是否包含主程序入口判断。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        if not isinstance(node.test.left, ast.Name) or node.test.left.id != "__name__":
            continue
        if any(isinstance(value, ast.Constant) and value.value == "__main__" for value in node.test.comparators):
            return True
    return False


def module_name(path, root) -> str:
    """将 Python 文件路径转换为本地模块名称。"""
    relative = path.relative_to(root).with_suffix("")
    if relative.name == "__init__":
        relative = relative.parent
    return ".".join(relative.parts) or path.stem


class PythonAnalyzer(Analyzer):
    """分析 Python import、入口和本地模块引用关系。"""

    name = "python"

    def analyze(self, context, state: AnalysisState) -> AnalysisResult:
        """从已扫描的 Python 文件中提取静态结构信息。"""
        files = [file for file in state.get_data("files", []) if file.language == Language.PYTHON]
        analysis = PythonAnalysis()
        warnings = []
        local_modules = {module_name(file.path, context.repository.root): file for file in files}

        for file in files:
            source = context.filesystem.read_text(file.path)
            if source is None:
                warnings.append(f"无法读取 Python 文件：{context.repository.relative_path(file.path)}")
                continue
            try:
                ast.parse(source)
            except SyntaxError as exc:
                warnings.append(f"Python 语法解析失败：{context.repository.relative_path(file.path)}（{exc.msg}）")
                continue

            imports = parse_imports(source)
            analysis.imports_by_file[file.path] = imports
            analysis.import_counts.update(imports)
            if file.path.name in ENTRY_FILE_NAMES:
                analysis.entry_points.append(EntryPoint(file.path, "文件名约定"))
            elif has_main_guard(source):
                analysis.entry_points.append(EntryPoint(file.path, '包含 __name__ == "__main__"'))

        for path, imports in analysis.imports_by_file.items():
            source_name = module_name(path, context.repository.root)
            for imported in imports:
                parts = imported.split(".")
                candidates = [imported]
                candidates.extend(".".join(parts[:index]) for index in range(len(parts) - 1, 0, -1))
                match = next((candidate for candidate in candidates if candidate in local_modules), None)
                if match:
                    analysis.local_references[match] += 1
                    analysis.dependencies.append(DependencyEdge(source_name, match))

        for name, file in local_modules.items():
            references = analysis.local_references[name]
            analysis.core_modules.append(ModuleSummary(name, file.non_empty_lines, references))
        analysis.core_modules.sort(key=lambda item: (item.lines + item.references * 10, item.name), reverse=True)
        return AnalysisResult(name=self.name, data=analysis, warnings=warnings)
