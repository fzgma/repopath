"""从 Python 语法提取有说明的定义、显式导出和保守的使用候选。"""

import ast
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..model.language import Language
from ..model.reading import ReadingEvidence, ReadingLocation
from ..model.result import AnalysisState, AnalyzerName
from .reading_support import MAX_FACTS, ReadingCollector

PythonDefinition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
ImportBinding = tuple[str, str, ast.Import | ast.ImportFrom]


@dataclass
class PythonFacts:
    """保存单个模块中有界且未经过执行求值的事实。"""

    path: str
    tree: ast.Module
    definitions: dict[str, list[PythonDefinition]] = field(
        default_factory=lambda: defaultdict[str, list[PythonDefinition]](
            list[PythonDefinition]
        )
    )
    imports: dict[str, list[ImportBinding]] = field(
        default_factory=lambda: defaultdict[str, list[ImportBinding]](
            list[ImportBinding]
        )
    )
    rebound: set[str] = field(default_factory=set[str])
    calls: list[ast.Call] = field(default_factory=list[ast.Call])


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
                module = alias.name if alias.asname else alias.name.split(".")[0]
                facts.imports[local].append((module, "", node))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > len(package):
                continue
            prefix = package[: len(package) - node.level + 1] if node.level else []
            base = ".".join(prefix + (node.module.split(".") if node.module else []))
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
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            facts.rebound.add(node.name)
            name = ".".join(scope + (node.name,))
            facts.definitions[name].append(node)
            scope += (node.name,)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            facts.rebound.add(node.id)
        elif isinstance(node, ast.arg):
            facts.rebound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and node not in tree.body:
            for alias in node.names:
                facts.rebound.add(alias.asname or alias.name.split(".")[0])
        if isinstance(node, ast.Call):
            facts.calls.append(node)
        pending.extend(
            (child, scope) for child in reversed(list(ast.iter_child_nodes(node)))
        )
    _imports(facts)
    return facts


def _definition(
    collector: ReadingCollector,
    facts: PythonFacts,
    name: str,
    node: PythonDefinition,
    topic: str,
    evidence: ReadingEvidence,
) -> None:
    """将有明确来源的定义转换为共用阅读步骤。"""
    location = collector.location(facts.path, node.lineno, node.end_lineno)
    evidence_items = [evidence]
    description = ast.get_docstring(node) or ""
    if description:
        document = node.body[0]
        evidence_items.append(
            ReadingEvidence(
                "python_docstring",
                collector.location(facts.path, document.lineno, document.end_lineno),
                description.split("\n\n", 1)[0][:240],
            )
        )
    collector.add(
        topic=topic,
        kind="definition",
        question="在哪里定义？",
        summary=f"{name} 的定义",
        location=location,
        evidence=tuple(evidence_items),
        learn=f"查看 {name} 的定义。"
        + (f"注释摘录：{description[:180]}" if description else ""),
    )


def _resolve_definition(
    facts: PythonFacts,
    name: str,
    files: dict[str, PythonFacts],
    modules: dict[str, list[str]],
    seen: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[PythonFacts, PythonDefinition] | None:
    """仅沿唯一的顶层导入追踪最多四层重导出，不求值动态名称。"""
    key = (facts.path, name)
    if key in seen or len(seen) >= 4:
        return None
    nodes = facts.definitions.get(name, [])
    if nodes:
        return (facts, nodes[0]) if len(nodes) == 1 else None
    bindings = facts.imports.get(name, [])
    if name in facts.rebound or len(bindings) != 1:
        return None
    module, imported, _ = bindings[0]
    targets = modules.get(module, [])
    if not imported or len(targets) != 1:
        return None
    return _resolve_definition(
        files[targets[0]], imported, files, modules, seen | {key}
    )


def _export_names(value: ast.expr | None) -> list[str] | None:
    """仅接受静态字符串列表或元组，不求值动态导出表达式。"""
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    names: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        names.append(item.value)
    return names


def _seed(
    collector: ReadingCollector,
    facts: PythonFacts,
    files: dict[str, PythonFacts],
    modules: dict[str, list[str]],
) -> set[str]:
    """只由文档字符串、显式导出或外部文档/清单形成阅读依据。"""
    interesting: set[str] = set()
    topic = f"源码位置：{facts.path}"
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
                ReadingEvidence("python_docstring", location, "模块文档字符串。"),
            ),
        )
    # 只有明确的导出或文档/清单关联才产生接口阅读目标。
    for node in facts.tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        names = _export_names(value)
        if names is None:
            collector.gap(
                "dynamic_export",
                "__all__ 并非静态字符串列表，未执行或求值导出规则。",
                facts.path,
            )
            continue
        for name in names:
            collector.check_cancelled()
            location = collector.location(facts.path, node.lineno, node.end_lineno)
            evidence = ReadingEvidence(
                "python_export", location, f"__all__ 列出 {name}。"
            )
            definitions = facts.definitions.get(name, [])
            resolved = _resolve_definition(facts, name, files, modules)
            related = tuple(
                collector.location(facts.path, target.lineno, target.end_lineno)
                for target in definitions[:6]
            )
            if resolved is not None:
                target_facts, target = resolved
                related = (
                    collector.location(
                        target_facts.path, target.lineno, target.end_lineno
                    ),
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
                question="导出列表列出了哪些名称？",
                summary=f"导出名称：{name}",
                location=location,
                evidence=(evidence,),
                related=related,
            )
            if resolved is not None:
                target_facts, target = resolved
                interesting.add(name)
                _definition(collector, target_facts, name, target, topic, evidence)
            else:
                collector.gap(
                    "unresolved_export",
                    "部分显式导出无法通过唯一顶层导入关联到定义；可能存在歧义、动态绑定或超出追踪范围。",
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
                (nodes[0].end_lineno or nodes[0].lineno) < anchor.line
                or nodes[0].lineno > (anchor.end_line or anchor.line)
            ):
                continue
            interesting.add(name)
            _definition(collector, facts, name, nodes[0], anchor.topic, anchor.evidence)
            if anchor.symbol and anchor.evidence.kind == "manifest_entry":
                target = collector.location(
                    facts.path, nodes[0].lineno, nodes[0].end_lineno
                )
                for key, step in collector.candidates.items():
                    if step.kind == "interface" and anchor.evidence in step.evidence:
                        collector.candidates[key] = replace(step, related=(target,))
    for node in facts.tree.body:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if not (
            isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            continue
        location = collector.location(facts.path, node.lineno, node.end_lineno)
        evidence = ReadingEvidence(
            "source_entry", location, "直接运行脚本时执行此分支。"
        )
        entry_related: list[ReadingLocation] = []
        for statement in node.body:
            if isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Call
            ):
                called = _attribute(statement.value.func)
                definitions = facts.definitions.get(called, [])
                if len(definitions) == 1:
                    target = definitions[0]
                    entry_related.append(
                        collector.location(facts.path, target.lineno, target.end_lineno)
                    )
        collector.add(
            topic=topic,
            kind="interface",
            question="哪里有脚本启动分支？",
            summary="脚本直接运行时的启动分支",
            location=location,
            evidence=(evidence,),
            related=tuple(entry_related),
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
    for record in sorted(
        state.artifacts.files,
        key=lambda record: (
            record.path.relative_to(collector.root).as_posix()
            not in collector.anchors_by_path
            if record.path.is_relative_to(collector.root)
            else True,
            record.path.as_posix(),
        ),
    ):
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
        path: _seed(collector, facts, files, modules) for path, facts in files.items()
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
            resolved = _resolve_definition(files[target_path], name, files, modules)
            if name not in interests[target_path] or resolved is None:
                continue
            target_facts, definition = resolved
            location = collector.location(path, call.lineno, call.end_lineno)
            target = collector.location(
                target_facts.path, definition.lineno, definition.end_lineno
            )
            collector.add(
                topic=f"源码位置：{target_path}",
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
