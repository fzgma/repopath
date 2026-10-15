"""复用 C++ 词法事实，为明确引用的文件提供有限片段和候选关联。"""

from collections import defaultdict
from dataclasses import dataclass

from ..model.reading import ReadingEvidence
from ..model.result import AnalysisState, AnalyzerName
from .cpp.analyzer import FUNCTION_PATTERN
from .cpp.includes import scan_source
from .reading_support import MAX_FACTS, Anchor, ReadingCollector


@dataclass(frozen=True)
class CppFragment:
    """保留已有函数识别结果对应的词法范围，不声称完整类型绑定。"""

    name: str
    line: int
    end_line: int
    definition: bool


def _fragments(collector: ReadingCollector, path: str) -> list[CppFragment]:
    """使用屏蔽字面量的源码确定声明或配对大括号片段范围。"""
    source = collector.read(path)
    if source is None:
        return []
    parsed = scan_source(source)
    fragments: list[CppFragment] = []
    for match in FUNCTION_PATTERN.finditer(parsed.code):
        collector.check_cancelled()
        if len(fragments) >= MAX_FACTS:
            collector.guide.truncated = True
            collector.gap("fact_budget", "C++ 片段达到导读预算。", path)
            break
        line, _ = parsed.location(match.start(1))
        end = match.end() - 1
        definition = match.group("ending") == "{"
        if definition:
            depth = 1
            while depth and end + 1 < len(parsed.code):
                end += 1
                if end % 256 == 0:
                    collector.check_cancelled()
                if parsed.code[end] == "{":
                    depth += 1
                elif parsed.code[end] == "}":
                    depth -= 1
            if depth:
                collector.gap(
                    "incomplete_cpp",
                    "函数括号范围不完整，未把尾部源码作为完整定义。",
                    path,
                )
                continue
        end_line, _ = parsed.location(end)
        fragments.append(
            CppFragment(
                match.group(1).split("::")[-1], line, end_line, definition
            )
        )
    return fragments


def collect_cpp(collector: ReadingCollector, state: AnalysisState) -> None:
    """仅沿文档/清单显式引用和已有 include 关系扩展，不按入口名猜主线。"""
    result = state.results.get(AnalyzerName.CPP)
    if (
        not collector.context.options.cpp_enabled
        or result is None
        or not result.successful
    ):
        collector.gap(
            "cpp_unavailable",
            "C++ 深入导读未启用或分析未成功；仍可使用文档和清单导航。",
        )
        return
    collector.guide.capabilities.append(
        "C++：文档关联片段、include 和同名定义候选；未分析宏、重载或类型。"
    )
    for entry in state.artifacts.cpp.entry_points:
        if not entry.path.is_relative_to(collector.root):
            continue
        path = entry.path.relative_to(collector.root).as_posix()
        location = collector.location(path, entry.line, entry.line)
        collector.anchor(Anchor(
            path, f"程序入口：{path}",
            ReadingEvidence("source_entry", location, f"源码中的 {entry.name} 入口候选。"),
            symbol=entry.name,
        ))
    anchors: dict[str, list[Anchor]] = defaultdict(list)
    for anchor in collector.anchors:
        anchors[anchor.path].append(anchor)
    items = {
        path.relative_to(collector.root).as_posix(): item
        for path, item in state.artifacts.cpp.files.items()
        if path.is_relative_to(collector.root)
        and path.relative_to(collector.root).as_posix() in collector.paths
    }
    fragments: dict[str, list[CppFragment]] = {}
    for path in sorted(anchors):
        if path not in items:
            continue
        fragments[path] = _fragments(collector, path)
        known = {
            (symbol.name, symbol.line) for symbol in items[path].functions
        }
        for fragment in fragments[path]:
            if (fragment.name, fragment.line) not in known:
                continue
            for anchor in anchors[path]:
                if anchor.symbol and fragment.name != anchor.symbol:
                    continue
                if not collector.relation():
                    return
                if anchor.line is not None and (
                    fragment.end_line < anchor.line
                    or fragment.line > (anchor.end_line or anchor.line)
                ):
                    continue
                location = collector.location(
                    path, fragment.line, fragment.end_line
                )
                collector.add(
                    topic=anchor.topic,
                    kind="definition" if fragment.definition else "interface",
                    question="文档关联了哪些声明或定义？",
                    summary=f"{fragment.name} 的{'定义' if fragment.definition else '声明'}候选",
                    location=location,
                    confidence="candidate",
                    evidence=(
                        anchor.evidence,
                        ReadingEvidence(
                            "cpp_symbol",
                            location,
                            "源码中的同名符号片段。",
                        ),
                    ),
                )
    for path, item in items.items():
        collector.check_cancelled()
        for include in item.include_details:
            if include.target is None or not include.target.is_relative_to(
                collector.root
            ):
                continue
            target_path = include.target.relative_to(collector.root).as_posix()
            if target_path not in fragments or not fragments[target_path]:
                continue
            if path not in fragments:
                fragments[path] = _fragments(collector, path)
            for anchor in anchors[target_path]:
                if not collector.relation():
                    return
                location = collector.location(path, include.line, include.line)
                evidence = ReadingEvidence(
                    "cpp_include",
                    location,
                    "include 路径指向文档引用的文件。",
                )
                collector.add(
                    topic=anchor.topic,
                    kind="usage",
                    question="哪些文件包含它？",
                    summary=f"源码包含 {include.name}",
                    location=location,
                    evidence=(anchor.evidence, evidence),
                    related=(collector.location(target_path),),
                )
                declarations = {
                    fragment.name
                    for fragment in fragments[target_path]
                    if not fragment.definition
                    and (
                        anchor.line is None
                        or (
                            fragment.end_line >= anchor.line
                            and fragment.line
                            <= (anchor.end_line or anchor.line)
                        )
                    )
                }
                matches = [
                    fragment
                    for fragment in fragments[path]
                    if fragment.definition and fragment.name in declarations
                ]
                for fragment in matches:
                    if not collector.relation():
                        return
                    candidates = [
                        item for item in matches if item.name == fragment.name
                    ]
                    declared = [
                        item
                        for item in fragments[target_path]
                        if item.name == fragment.name and not item.definition
                    ]
                    if len(candidates) > 1 or len(declared) > 1:
                        collector.gap(
                            "ambiguous_cpp_symbol",
                            "同名声明或定义有多个候选，未确定重载、命名空间或实际绑定。",
                            path,
                        )
                    if len(declared) > 6:
                        collector.gap(
                            "related_limit",
                            "同名声明超过 6 个，仅保留前 6 个关联位置；未确定绑定。",
                            path,
                        )
                    location = collector.location(
                        path, fragment.line, fragment.end_line
                    )
                    collector.add(
                        topic=anchor.topic,
                        kind="definition",
                        question="有哪些同名定义候选？",
                        summary=f"{fragment.name} 的同名定义候选",
                        location=location,
                        confidence="candidate",
                        evidence=(anchor.evidence, evidence),
                        related=tuple(
                            collector.location(
                                target_path, item.line, item.end_line
                            )
                            for item in declared[:6]
                        ),
                    )
