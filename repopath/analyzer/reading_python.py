"""从 Python 语法提取有说明的定义、显式导出和保守的使用候选。"""

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..model.language import Language
from ..model.reading import ReadingEvidence
from ..model.result import AnalysisState, AnalyzerName
from .reading_support import MAX_FACTS, ReadingCollector


@dataclass
class PythonFacts:
    """保存单个模块中有界且未经过执行求值的事实。"""

    path: str
    tree: ast.Module
    definitions: dict[str, list[ast.AST]] = field(
        default_factory=lambda: defaultdict(list)
    )
    imports: dict[str, list[tuple[str, str, ast.AST]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    rebound: set[str] = field(default_factory=set)
    calls: list[ast.Call] = field(default_factory=list)


def _attribute(node: ast.AST) -> str:
    """只识别名称与点号访问，不求值索引、调用和动态属性。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    return ".".join([node.id] + list(reversed(parts)))


def _module(path: str) -> str:
    """按源码相对路径记录模块候选，不推断运行时搜索路径。"""
    parts = list(Path(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(facts: PythonFacts) -> None:
    """仅使用模块顶层直接导入；条件和局部导入留作未知。"""
    package = _module(facts.path).split(".")
    if not facts.path.endswith("/__init__.py") and facts.path != "__init__.py":
        package = package[:-1]
    for node in facts.tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                # import a.b 在使用处保留完整属性路径，避免把 a 当作 b。
                module = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
                facts.imports[local].append((module, "", node))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > len(package):
                continue
            prefix = (
                package[: len(package) - node.level + 1] if node.level else []
            )
            base = ".".join(
                prefix + (node.module.split(".") if node.module else [])
            )
            for alias in node.names:
                if alias.name != "*":
                    facts.imports[alias.asname or alias.name].append(
                        (base, alias.name, node)
                    )


def _parse(collector: ReadingCollector, path: str) -> PythonFacts | None:
    """遍历有界语法树并保存词法作用域，局部失败不影响其他模块。"""
    source = collector.read(path)
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        collector.gap(
            "invalid_python",
            "Python 语法无法解析，未生成该文件的符号解释。",
            path,
        )
        return None
    facts = PythonFacts(path, tree)
    pending: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
    count = 0
    while pending:
        collector.check_cancelled()
        node, scope = pending.pop()
        count += 1
        if count > MAX_FACTS:
            collector.guide.truncated = True
            collector.gap(
                "fact_budget",
                "Python 语法节点超过导读预算，跳过不完整的文件关联。",
                path,
            )
            return None
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            facts.rebound.add(node.name)
            name = ".".join(scope + (node.name,))
            facts.definitions[name].append(node)
            scope += (node.name,)
        elif isinstance(node, ast.Name) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            facts.rebound.add(node.id)
        elif isinstance(node, ast.arg):
            facts.rebound.add(node.arg)
        elif (
            isinstance(node, (ast.Import, ast.ImportFrom))
            and node not in tree.body
        ):
            for alias in node.names:
                facts.rebound.add(alias.asname or alias.name.split(".")[0])
        if isinstance(node, ast.Call):
            facts.calls.append(node)
        pending.extend(
            (child, scope)
            for child in reversed(list(ast.iter_child_nodes(node)))
        )
    _imports(facts)
    return facts


def _definition(
    collector: ReadingCollector,
    facts: PythonFacts,
    name: str,
    node: ast.AST,
    topic: str,
    evidence: ReadingEvidence,
) -> None:
    """将有明确来源的定义转换为共用阅读步骤。"""
    location = collector.location(facts.path, node.lineno, node.end_lineno)
    collector.add(
        topic=topic,
        kind="definition",
        question="在哪里定义？",
        summary=f"{name} 的定义",
        location=location,
        evidence=(evidence,),
    )


def _seed(
    collector: ReadingCollector,
    facts: PythonFacts,
) -> set[str]:
    """只由文档字符串、显式导出或外部文档/清单形成阅读依据。"""
    interesting: set[str] = set()
    topic = f"源码说明：{facts.path}"
    if ast.get_docstring(facts.tree):
        node = facts.tree.body[0]
        location = collector.location(facts.path, node.lineno, node.end_lineno)
        collector.add(
            topic=topic,
            kind="document",
            question="模块如何介绍？",
            summary="作者提供的模块说明。",
            location=location,
            confidence="documented",
            evidence=(
                ReadingEvidence(
                    "python_docstring", location, "模块文档字符串。"
                ),
            ),
        )
    for name, nodes in facts.definitions.items():
        for node in nodes:
            if not ast.get_docstring(node):
                continue
            document = node.body[0]
            evidence = ReadingEvidence(
                "python_docstring",
                collector.location(
                    facts.path, document.lineno, document.end_lineno
                ),
                f"{name} 的文档字符串。",
            )
            interesting.add(name)
            _definition(collector, facts, name, node, topic, evidence)
    for node in facts.tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple)) or not all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in value.elts
        ):
            collector.gap(
                "dynamic_export",
                "__all__ 并非静态字符串列表，未执行或求值导出规则。",
                facts.path,
            )
            continue
        for item in value.elts:
            collector.check_cancelled()
            name = item.value
            location = collector.location(
                facts.path, node.lineno, node.end_lineno
            )
            evidence = ReadingEvidence(
                "python_export", location, f"__all__ 列出 {name}。"
            )
            definitions = facts.definitions.get(name, [])
            related = tuple(
                collector.location(
                    facts.path, target.lineno, target.end_lineno
                )
                for target in definitions[:6]
            )
            if len(definitions) > 6:
                collector.gap(
                    "related_limit",
                    "显式导出的同名定义超过 6 个，仅保留前 6 个位置；未确定绑定。",
                    facts.path,
                )
            collector.add(
                topic=topic,
                kind="interface",
                question="显式导出了什么？",
                summary=f"__all__ 列出 {name}",
                location=location,
                evidence=(evidence,),
                related=related,
            )
            if len(definitions) == 1:
                interesting.add(name)
                _definition(
                    collector, facts, name, definitions[0], topic, evidence
                )
            else:
                collector.gap(
                    "unresolved_export",
                    "部分显式导出未能唯一关联到本文件定义；重导出或动态赋值尚未追踪。",
                    facts.path,
                )
    for anchor in collector.anchors_by_path[facts.path]:
        definitions = (
            facts.definitions.items()
            if not anchor.symbol
            else [(anchor.symbol, facts.definitions.get(anchor.symbol, []))]
        )
        for name, nodes in definitions:
            if not collector.relation():
                return interesting
            if len(nodes) != 1:
                collector.gap(
                    "ambiguous_symbol",
                    "文档或清单指向的符号没有唯一的语法定义，未选定目标。",
                    facts.path,
                )
                continue
            if anchor.line is not None and (
                nodes[0].end_lineno < anchor.line
                or nodes[0].lineno > (anchor.end_line or anchor.line)
            ):
                continue
            interesting.add(name)
            _definition(
                collector, facts, name, nodes[0], anchor.topic, anchor.evidence
            )
    return interesting


def collect_python(collector: ReadingCollector, state: AnalysisState) -> None:
    """成功启用 Python 分析时才补充语法事实；无需依赖图。"""
    result = state.results.get(AnalyzerName.PYTHON)
    if (
        not collector.context.options.python_enabled
        or result is None
        or not result.successful
    ):
        collector.gap(
            "python_unavailable",
            "Python 深入导读未启用或分析未成功；仍可使用文档和清单导航。",
        )
        return
    collector.guide.capabilities.append(
        "Python：文档说明、显式导出、定义和静态导入的使用候选。"
    )
    files: dict[str, PythonFacts] = {}
    for record in state.artifacts.files:
        if record.language != Language.PYTHON:
            continue
        if not record.path.is_relative_to(collector.root):
            continue
        path = record.path.relative_to(collector.root).as_posix()
        if path not in collector.paths:
            continue
        facts = _parse(collector, path)
        if facts is not None:
            files[path] = facts
    modules: dict[str, list[str]] = defaultdict(list)
    for path in files:
        modules[_module(path)].append(path)
    interests = {
        path: _seed(collector, facts) for path, facts in files.items()
    }
    for path, facts in files.items():
        for call in facts.calls:
            collector.check_cancelled()
            qualified = _attribute(call.func)
            if not qualified:
                continue
            root, _, rest = qualified.partition(".")
            bindings = facts.imports.get(root, [])
            if root in facts.rebound or len(bindings) != 1:
                continue
            if not collector.relation():
                return
            module, imported, import_node = bindings[0]
            name = ".".join(part for part in (imported, rest) if part)
            target_paths = modules.get(module, [])
            # from package import module / import package.module 的完整模块前缀。
            while not target_paths and "." in name:
                first, _, name = name.partition(".")
                module = module + "." + first if module else first
                target_paths = modules.get(module, [])
            if len(target_paths) != 1:
                continue
            target_path = target_paths[0]
            nodes = files[target_path].definitions.get(name, [])
            if name not in interests[target_path] or len(nodes) != 1:
                continue
            definition = nodes[0]
            location = collector.location(path, call.lineno, call.end_lineno)
            target = collector.location(
                target_path, definition.lineno, definition.end_lineno
            )
            collector.add(
                topic=f"源码说明：{target_path}",
                kind="usage",
                question="在哪里使用？",
                summary=f"{qualified}(...) 的使用候选",
                location=location,
                confidence="candidate",
                related=(target,),
                evidence=(
                    ReadingEvidence(
                        "python_import",
                        collector.location(
                            path, import_node.lineno, import_node.end_lineno
                        ),
                        "对应的模块顶层导入。",
                    ),
                    ReadingEvidence(
                        "python_call_expression",
                        location,
                        f"源码中的 {qualified}(...) 表达式。",
                    ),
                ),
            )
