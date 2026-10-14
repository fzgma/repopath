"""从 Markdown 和静态清单提取显式导航，不执行清单中的代码。"""

import json
import re

import tomllib

from ..model.reading import ReadingEvidence
from .reading_support import MAX_FACTS, Anchor, ReadingCollector

_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")
_LINK = re.compile(
    r"(?<!!)\[[^\]\n]+\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+[^)]*)?\)"
)
_REFERENCE = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)")
_LINE = re.compile(r"L?(\d+)(?:-L?(\d+))?$", re.IGNORECASE)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INLINE_CODE = re.compile(r"(`+).*?\1")


def collect_documents(collector: ReadingCollector) -> None:
    """所有 Markdown 文件采用同一规则，不依赖约定目录或项目名称。"""
    for path in sorted(collector.paths):
        if not path.lower().endswith(".md"):
            continue
        source = collector.read(path)
        if source is None:
            continue
        lines = collector.lines(path)
        headings: list[tuple[int, str]] = []
        links: list[tuple[int, str]] = []
        fence = ""
        for number, line in enumerate(lines, 1):
            collector.check_cancelled()
            fence_match = _FENCE.match(line)
            if fence:
                if (
                    fence_match
                    and fence_match.group(1)[0] == fence[0]
                    and len(fence_match.group(1)) >= len(fence)
                    and not fence_match.group(2).strip()
                ):
                    fence = ""
                continue
            if fence_match and not (
                fence_match.group(1)[0] == "`" and "`" in fence_match.group(2)
            ):
                fence = fence_match.group(1)
                continue
            if line.startswith(("    ", "\t")):
                continue
            heading = _HEADING.match(line)
            if heading:
                headings.append((number, heading.group(2)))
            text = _INLINE_CODE.sub("", line)
            for match in _LINK.finditer(text):
                links.append((number, match.group(1).strip("<>")))
            reference = _REFERENCE.match(line)
            if reference:
                links.append((number, reference.group(1).strip("<>")))
            if len(headings) + len(links) >= MAX_FACTS:
                collector.guide.truncated = True
                collector.gap("fact_budget", "文档证据达到数量上限。", path)
                break
        if not source.strip():
            continue
        if not headings:
            headings = [(1, "文档正文")]
        topic = f"文档：{path}"
        for index, (line, title) in enumerate(headings):
            end = (
                headings[index + 1][0] - 1
                if index + 1 < len(headings)
                else len(lines)
            )
            location = collector.location(path, line, end)
            evidence = ReadingEvidence(
                "document_section",
                location,
                f"文档章节：{title[:160]}",
            )
            collector.add(
                topic=topic,
                kind="document",
                question="文档如何介绍？",
                summary=f"作者说明：“{title[:160]}”",
                location=location,
                evidence=(evidence,),
                confidence="documented",
            )
        for line, target in links:
            collector.check_cancelled()
            resolved = collector.resolve(path, target)
            if resolved is None:
                continue
            destination, fragment = resolved
            source_location = collector.location(path, line, line)
            evidence = ReadingEvidence(
                "document_link", source_location, "文档中的本地链接。"
            )
            target_line, target_end = 1, None
            line_match = _LINE.fullmatch(fragment)
            if line_match:
                target_line = int(line_match.group(1))
                target_end = int(line_match.group(2) or target_line)
                target_source = collector.read(destination)
                if target_source is None:
                    continue
                if (
                    not 1
                    <= target_line
                    <= target_end
                    <= max(1, len(collector.lines(destination)))
                ):
                    collector.gap(
                        "unresolved_fragment",
                        "链接行号超出当前文件范围，未猜测位置。",
                        path,
                    )
                    continue
            elif fragment:
                collector.gap(
                    "unresolved_fragment",
                    "仅定位到链接文件；未解析命名锚点。",
                    path,
                )
            if collector.read(destination) is None:
                continue
            if not fragment or line_match:
                collector.anchor(
                    Anchor(
                        destination,
                        topic,
                        evidence,
                        line=target_line if line_match else None,
                        end_line=target_end,
                    )
                )
            collector.add(
                topic=topic,
                kind="document",
                question="文档指向哪里？",
                summary="文档链接指向此文件。",
                location=collector.location(
                    destination, target_line, target_end
                ),
                evidence=(evidence,),
            )


def _value_line(source: str, value: str) -> int:
    """仅在字面值唯一出现时给出具体行，否则定位整个清单。"""
    offset = source.find(value)
    return (
        source.count("\n", 0, offset) + 1
        if offset >= 0 and source.find(value, offset + 1) < 0
        else 1
    )


def _module_paths(
    collector: ReadingCollector, manifest: str, module: str
) -> list[str]:
    """按完整模块后缀找候选，不假定 src 布局或求值构建配置。"""
    directory = manifest.rsplit("/", 1)[0] + "/" if "/" in manifest else ""
    suffixes = (
        module.replace(".", "/") + ".py",
        module.replace(".", "/") + "/__init__.py",
    )
    return [
        path
        for path in sorted(collector.paths)
        if path.startswith(directory)
        and any(
            path[len(directory) :] == suffix
            or path[len(directory) :].endswith("/" + suffix)
            for suffix in suffixes
        )
    ]


def _manifest_target(
    collector: ReadingCollector,
    path: str,
    source: str,
    name: str,
    target: str,
    *,
    python: bool = False,
) -> None:
    """记录声明本身；仅唯一的静态路径候选才加入关联。"""
    if not target or len(target) > 1000:
        return
    location = collector.location(path, _value_line(source, target))
    evidence = ReadingEvidence(
        "manifest_entry",
        location,
        f"清单声明：{name[:120]} = {target[:160]}",
    )
    topic = f"清单：{path}"
    related = ()
    symbol = ""
    if python:
        match = re.fullmatch(
            r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
            target,
        )
        targets = (
            _module_paths(collector, path, match.group(1)) if match else []
        )
        symbol = match.group(2) if match else ""
        if not match:
            collector.gap(
                "unsupported_entry",
                "Python 入口并非简单 module:symbol 字面值，未求值。",
                path,
            )
    else:
        if any(character in target for character in "*?{"):
            collector.gap(
                "unsupported_entry", "清单包含通配或模板路径，未展开。", path
            )
            targets = []
        else:
            resolved = collector.resolve(path, target)
            targets = [resolved[0]] if resolved else []
    if len(targets) == 1:
        destination = targets[0]
        collector.anchor(Anchor(destination, topic, evidence, symbol))
        if collector.read(destination) is not None:
            related = (collector.location(destination),)
    elif len(targets) > 1:
        collector.gap(
            "ambiguous_entry",
            "同一清单入口对应多个文件候选，未选择其中一个。",
            path,
        )
    elif python:
        collector.gap(
            "unresolved_entry",
            "入口声明未能唯一关联到已扫描文件；未猜测安装后的模块路径。",
            path,
        )
    collector.add(
        topic=topic,
        kind="interface",
        question="清单声明了什么？",
        summary=f"{name[:100]} 声明 {target[:160]}",
        location=location,
        evidence=(evidence,),
        related=related,
    )


def collect_manifests(collector: ReadingCollector) -> None:
    """只读取受限字段；忽略安装脚本、依赖下载和动态配置。"""
    for path in sorted(collector.paths):
        name = path.rsplit("/", 1)[-1]
        if name not in {"pyproject.toml", "package.json"}:
            continue
        source = collector.read(path)
        if source is None:
            continue
        try:
            data = (
                tomllib.loads(source)
                if name == "pyproject.toml"
                else json.loads(source)
            )
        except (ValueError, RecursionError):
            collector.gap(
                "invalid_manifest",
                "清单格式无法解析，已跳过其入口声明。",
                path,
            )
            continue
        if not isinstance(data, dict):
            collector.gap(
                "invalid_manifest", "清单顶层不是对象，未推断入口。", path
            )
            continue
        if name == "pyproject.toml":
            project = data.get("project", {})
            if not isinstance(project, dict):
                continue
            for field in ("scripts", "gui-scripts"):
                entries = project.get(field, {})
                if not isinstance(entries, dict):
                    continue
                for command, target in entries.items():
                    collector.check_cancelled()
                    if isinstance(target, str):
                        _manifest_target(
                            collector,
                            path,
                            source,
                            f"{field}.{command}",
                            target,
                            python=True,
                        )
        else:
            count = 0
            pending = [
                (field, data[field], 0)
                for field in ("main", "module", "types", "bin", "exports")
                if field in data
            ]
            while pending:
                collector.check_cancelled()
                field, value, depth = pending.pop(0)
                count += 1
                if count > MAX_FACTS or depth > 12:
                    collector.guide.truncated = True
                    collector.gap(
                        "fact_budget", "清单入口嵌套或数量超出导读预算。", path
                    )
                    continue
                if isinstance(value, str):
                    _manifest_target(collector, path, source, field, value)
                elif isinstance(value, dict):
                    pending.extend(
                        (f"{field}.{key}", item, depth + 1)
                        for key, item in value.items()
                    )
                elif isinstance(value, list):
                    pending.extend(
                        (f"{field}[{index}]", item, depth + 1)
                        for index, item in enumerate(value)
                    )
