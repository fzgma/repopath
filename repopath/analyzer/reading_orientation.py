"""从作者说明、项目清单和包边界建立导读上下文。"""

import ast
import re
from pathlib import PurePosixPath

from ..model.reading import ReadingComponent, ReadingEvidence
from .reading_manifest import load_manifest, manifest_fields
from .reading_support import ReadingCollector

MAX_COMPONENTS = 20
MAX_MANIFESTS = 64
_STRUCTURE = re.compile(
    r"架构|组成|结构|architecture|components|structure|design", re.IGNORECASE
)
_USAGE = re.compile(
    r"用法|使用|入门|快速开始|示例|usage|getting.started|quick.start|example",
    re.IGNORECASE,
)
_PURPOSE = re.compile(
    r"介绍|概览|功能|能力|overview|introduction|features|about", re.IGNORECASE
)
_MAINTENANCE = re.compile(
    r"贡献|许可|变更日志|更新日志|致谢|contribut|licen[sc]e|changelog|credits",
    re.IGNORECASE,
)


def document_goal(title: str) -> str:
    """标题只用于选择阅读问题，不据此编造项目职责。"""
    for pattern, goal in (
        (_MAINTENANCE, "maintenance"),
        (_STRUCTURE, "structure"),
        (_USAGE, "usage"),
        (_PURPOSE, "purpose"),
    ):
        if pattern.search(title):
            return goal
    return "document"


def prose(lines: list[str], start: int = 1, end: int | None = None) -> tuple[int, str]:
    """提取第一个正文段落，跳过标题、徽章、HTML 和代码围栏。"""
    result: list[str] = []
    first = 0
    fence = ""
    for number in range(start, min(end or len(lines), len(lines)) + 1):
        line = lines[number - 1].strip()
        marker = re.match(r"(`{3,}|~{3,})", line)
        if marker:
            if not fence:
                fence = marker.group()[0]
            elif marker.group()[0] == fence:
                fence = ""
            continue
        if fence:
            continue
        if not line:
            if result:
                break
            continue
        if line.startswith(("#", "<", "!", "|", "[", "<!--")):
            if result:
                break
            continue
        if line.startswith(("- ", "* ", "> ")):
            if result:
                break
            continue
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        text = re.sub(r"<[^>]*>", "", text).replace("**", "").strip()
        without_links = re.sub(r"\[[^\]]+\]\([^)]+\)", "", line).strip()
        if not result and (
            len(text) < 8 or without_links != line and len(without_links) < 12
        ):
            continue
        first = first or number
        result.append(text)
        if len(" ".join(result)) >= 360:
            break
    return first, " ".join(result)[:480]


def _description(collector: ReadingCollector, path: str, value: str) -> ReadingEvidence:
    source = collector.read(path) or ""
    offset = source.find(value)
    line = source.count("\n", 0, offset) + 1 if offset >= 0 else 1
    return ReadingEvidence(
        "project_description",
        collector.location(path, line, line),
        value[:480],
    )


def collect_orientation(collector: ReadingCollector) -> None:
    """先读项目清单及其说明，预留预算后再扫描普通源码。"""
    manifests = sorted(
        (
            p
            for p in collector.paths
            if PurePosixPath(p).name in {"pyproject.toml", "package.json"}
        ),
        key=lambda p: (p.count("/"), p),
    )
    components: dict[str, ReadingComponent] = {}
    if len(manifests) > MAX_MANIFESTS:
        collector.gap("read_budget", "项目清单超过导读预算，尚未覆盖全部子项目。")
    for path in manifests[:MAX_MANIFESTS]:
        collector.check_cancelled()
        source = collector.read(path)
        if source is None:
            continue
        try:
            data = manifest_fields(
                load_manifest(source, toml=path.endswith(".toml"))
            )
        except (ValueError, RecursionError):
            continue
        if data is None:
            continue
        project = manifest_fields(data.get("project")) if path.endswith(".toml") else data
        if not project:
            continue
        directory = str(PurePosixPath(path).parent)
        name = project.get("name")
        description_value = project.get("description")
        description = description_value if isinstance(description_value, str) else ""
        manifest_evidence: tuple[ReadingEvidence, ...] = ()
        if description.strip():
            statement = _description(collector, path, description.strip())
            manifest_evidence = (statement,)
            if directory == ".":
                collector.guide.purpose.append(statement)
        if directory != ".":
            components[directory] = ReadingComponent(
                directory,
                name if isinstance(name, str) else directory,
                description[:480] if manifest_evidence else "独立项目清单；尚无用途说明。",
                manifest_evidence[0].location
                if manifest_evidence
                else collector.location(path, 1, 1),
                manifest_evidence,
            )
        readme = project.get("readme")
        readme_fields = manifest_fields(readme)
        if readme_fields is not None:
            readme = readme_fields.get("file")
        if isinstance(readme, str):
            resolved = collector.resolve(path, readme)
            if resolved:
                collector.overview_paths.add(resolved[0])
                if directory == ".":
                    collector.primary_documents.add(resolved[0])
    # README 是文档约定；被清单显式指定的其他文件名同样有效。
    for path in collector.paths:
        name = PurePosixPath(path).name.lower()
        if name in {
            "readme.md",
            "readme.markdown",
            "readme.rst",
            "readme.txt",
            "readme",
        }:
            collector.overview_paths.add(path)
    overview = sorted(collector.overview_paths, key=lambda p: (p.count("/"), p))
    if not collector.primary_documents:
        collector.primary_documents.update(p for p in overview if "/" not in p)
    overview.sort(key=lambda p: (p not in collector.primary_documents, p.count("/"), p))
    if len(overview) > MAX_COMPONENTS:
        collector.gap("read_budget", "组件说明文档超过导读预算，尚未覆盖全部说明。")
    for path in overview[:MAX_COMPONENTS]:
        if collector.read(path) is None:
            continue
        line, description = prose(collector.lines(path))
        if not description:
            continue
        document_evidence = ReadingEvidence(
            "project_document",
            collector.location(path, line),
            description,
        )
        directory = str(PurePosixPath(path).parent)
        if path in collector.primary_documents:
            if len(collector.guide.purpose) < 2:
                collector.guide.purpose.append(document_evidence)
        elif directory in components:
            item = components[directory]
            if not item.evidence:
                components[directory] = ReadingComponent(
                    directory,
                    item.name,
                    description,
                    document_evidence.location,
                    (document_evidence,),
                )
    # 选择最外层包，以及该包的直接子包；避免列举每个深层实现目录。
    packages = {
        str(PurePosixPath(path).parent): path
        for path in collector.paths
        if path.endswith("/__init__.py")
    }
    outer = {
        p
        for p in packages
        if not any(str(parent) in packages for parent in PurePosixPath(p).parents)
    }
    selected = outer | {p for p in packages if str(PurePosixPath(p).parent) in outer}
    # 包的直接子目录也可能采用 namespace 布局，不要求每层都有 __init__.py。
    for path in sorted(collector.paths):
        collector.check_cancelled()
        if not path.endswith(".py"):
            continue
        parts = PurePosixPath(path).parts
        for index in range(1, len(parts) - 1):
            if "/".join(parts[:index]) in outer:
                directory = "/".join(parts[: index + 1])
                selected.add(directory)
                packages.setdefault(directory, path)
                break
    for directory in sorted(selected, key=lambda p: (p.count("/"), p)):
        if len(components) >= MAX_COMPONENTS:
            collector.gap("component_limit", "组成部分超过展示上限，其余部分尚未列出。")
            break
        if directory in components:
            continue
        if any(directory.startswith(p + "/") for p in components if p not in outer):
            continue
        path = packages[directory]
        source = collector.read(path)
        if source is None:
            continue
        package_file = path == directory + "/__init__.py"
        description = (
            "Python 包；尚无职责说明。"
            if package_file
            else "包内源码目录；尚无职责说明。"
        )
        package_evidence: tuple[ReadingEvidence, ...] = ()
        tree: ast.Module | None = None
        try:
            tree = (
                ast.parse(source)
                if collector.python_available and package_file
                else None
            )
            doc = ast.get_docstring(tree) if tree is not None else None
        except (SyntaxError, ValueError, RecursionError):
            doc = None
        if doc and tree is not None:
            node = tree.body[0]
            package_evidence = (
                ReadingEvidence(
                    "python_docstring",
                    collector.location(path, node.lineno, node.end_lineno),
                    doc.split("\n\n", 1)[0][:480],
                ),
            )
            description = package_evidence[0].description
        components[directory] = ReadingComponent(
            directory,
            PurePosixPath(directory).name,
            description,
            collector.location(path, 1, 1),
            package_evidence,
        )
    # 未有包或清单的目录只提供结构事实；不按 services/utils 等名字推断职责。
    directories: dict[str, set[str]] = {}
    for path in collector.paths:
        parts = PurePosixPath(path).parts
        if len(parts) < 2 or parts[0].startswith("."):
            continue
        if PurePosixPath(path).suffix.lower() not in {
            ".py",
            ".cpp",
            ".cc",
            ".c",
            ".h",
            ".hpp",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".rs",
            ".go",
            ".java",
            ".cs",
        }:
            continue
        directories.setdefault(parts[0], set()).add(path)
    for directory, paths in sorted(directories.items()):
        if directory in components or any(
            p.startswith(directory + "/") for p in components
        ):
            continue
        if len(components) >= MAX_COMPONENTS:
            collector.gap("component_limit", "组成部分超过展示上限，其余部分尚未列出。")
            break
        path = min(paths)
        components[directory] = ReadingComponent(
            directory,
            directory,
            "源码目录；未找到可引用的职责说明。",
            collector.location(path, 1, 1),
        )
    collector.guide.components = list(components.values())[:MAX_COMPONENTS]
    if len(components) > MAX_COMPONENTS:
        collector.gap("component_limit", "组成部分超过展示上限，其余部分尚未列出。")
