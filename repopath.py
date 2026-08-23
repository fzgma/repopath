"""Generate a small, dependency-free overview of a source repository."""


import argparse
import ast
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


IGNORED_DIRS = {
    ".agents",
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cpp": "C++",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
}


@dataclass
class FileRecord:
    path: Path
    language: str
    lines: int
    non_empty_lines: int
    imports: list[str] = field(default_factory=list)
    is_entry_point: bool = False


@dataclass
class GitSummary:
    available: bool = False
    commit_count: int = 0
    authors: Counter[str] = field(default_factory=Counter)
    recent_commits: list[tuple[str, str, str, str]] = field(default_factory=list)
    changed_paths: Counter[str] = field(default_factory=Counter)


@dataclass
class Analysis:
    root: Path
    files: list[FileRecord]
    git: GitSummary


def parse_python_imports(source: str) -> list[str]:
    """解析 Python 源码并提取其中导入的模块名。"""
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
    """判断 Python 源码中是否包含主程序入口判断。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        left = node.test.left
        if not isinstance(left, ast.Name) or left.id != "__name__":
            continue
        if any(isinstance(value, ast.Constant) and value.value == "__main__" for value in node.test.comparators):
            return True
    return False


def is_ignored(path: Path, root: Path) -> bool:
    """判断文件路径是否位于需要跳过的目录中。"""
    return any(part in IGNORED_DIRS for part in path.relative_to(root).parts)


def read_source(path: Path) -> str | None:
    """以 UTF-8 编码读取文件内容，读取失败时返回空值。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def scan_files(root: Path, excluded_paths: set[Path]) -> list[FileRecord]:
    """扫描仓库文件并收集语言、行数、依赖和入口信息。"""
    records: list[FileRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or is_ignored(path, root) or path.resolve() in excluded_paths:
            continue

        source = read_source(path)
        if source is None:
            continue
        language = LANGUAGES.get(path.suffix.lower(), "Other")
        records.append(
            FileRecord(
                path=path,
                language=language,
                lines=len(source.splitlines()),
                non_empty_lines=sum(bool(line.strip()) for line in source.splitlines()),
                imports=parse_python_imports(source) if language == "Python" else [],
                is_entry_point=language == "Python" and (
                    path.name in {"main.py", "app.py", "cli.py", "manage.py", "__main__.py"}
                    or has_main_guard(source)
                ),
            )
        )
    return records


def run_git(root: Path, *args: str) -> str | None:
    """在指定仓库目录执行 Git 命令并返回标准输出。"""
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def collect_git_summary(root: Path) -> GitSummary:
    """收集仓库的提交数、贡献者、最近提交和高频修改路径。"""
    count_text = run_git(root, "rev-list", "--count", "HEAD")
    if count_text is None:
        return GitSummary()

    authors = Counter((run_git(root, "log", "--format=%an") or "").splitlines())
    commit_text = run_git(
        root,
        "log",
        "-n",
        "10",
        "--date=short",
        "--format=%h%x09%an%x09%ad%x09%s",
    )
    recent_commits = []
    for row in (commit_text or "").splitlines():
        fields = row.split("\t", 3)
        if len(fields) == 4:
            recent_commits.append(tuple(fields))

    changed_text = run_git(root, "log", "--format=", "--name-only") or ""
    changed_paths = Counter(path for path in changed_text.splitlines() if path.strip())
    return GitSummary(
        available=True,
        commit_count=int(count_text),
        authors=authors,
        recent_commits=recent_commits,
        changed_paths=changed_paths,
    )


def module_name(path: Path, root: Path) -> str:
    """将 Python 文件路径转换为模块名称。"""
    relative = path.relative_to(root).with_suffix("")
    if relative.name == "__init__":
        relative = relative.parent
    return ".".join(relative.parts) or path.stem


def local_module_references(files: list[FileRecord], root: Path) -> Counter[str]:
    """统计仓库内 Python 模块被其他文件导入的次数。"""
    local_modules = {module_name(file.path, root): file for file in files if file.language == "Python"}
    references: Counter[str] = Counter()
    for file in files:
        for imported in file.imports:
            candidates = [imported]
            parts = imported.split(".")
            candidates.extend(".".join(parts[:index]) for index in range(len(parts) - 1, 0, -1))
            match = next((candidate for candidate in candidates if candidate in local_modules), None)
            if match:
                references[match] += 1
    return references


def markdown_cell(value: object) -> str:
    """转义 Markdown 表格单元格中的特殊字符。"""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(analysis: Analysis) -> str:
    """根据分析结果生成 Markdown 格式的仓库报告。"""
    root, files, git = analysis.root, analysis.files, analysis.git
    language_counts = Counter(file.language for file in files)
    language_lines = Counter()
    directory_counts = Counter()
    import_counts = Counter()
    for file in files:
        language_lines[file.language] += file.non_empty_lines
        relative = file.path.relative_to(root)
        directory_counts[relative.parts[0] if len(relative.parts) > 1 else "."] += 1
        import_counts.update(file.imports)

    local_refs = local_module_references(files, root)
    core_modules = []
    for file in files:
        if file.language != "Python":
            continue
        name = module_name(file.path, root)
        references = local_refs[name]
        score = file.non_empty_lines + references * 10
        core_modules.append((score, name, file.non_empty_lines, references))

    total_lines = sum(file.non_empty_lines for file in files)
    report = [
        f"# RepoPath 报告：`{markdown_cell(root.name)}`",
        "",
        f"> 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "## 概览",
        "",
        f"- 文件数：{len(files)}",
        f"- 非空行数：{total_lines}",
        f"- 识别语言：{len(language_counts)}",
        f"- Python 入口候选：{sum(file.is_entry_point for file in files)}",
        "",
        "## 语言统计",
        "",
        "| 语言 | 文件数 | 非空行 | 文件占比 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for language, count in language_counts.most_common():
        percentage = count / len(files) * 100 if files else 0
        report.append(f"| {markdown_cell(language)} | {count} | {language_lines[language]} | {percentage:.1f}% |")

    report.extend(["", "## 主要目录", "", "| 目录 | 文件数 |", "| --- | ---: |"])
    for directory, count in directory_counts.most_common(15):
        report.append(f"| `{markdown_cell(directory)}` | {count} |")

    report.extend(["", "## 核心模块候选", "", "> 按非空行数和本地模块被引用次数进行轻量排序。", "", "| 模块 | 非空行 | 被引用 |", "| --- | ---: | ---: |"])
    if core_modules:
        for _, name, lines, references in sorted(core_modules, reverse=True)[:15]:
            report.append(f"| `{markdown_cell(name)}` | {lines} | {references} |")
    else:
        report.append("| 暂无 Python 模块 | 0 | 0 |")

    report.extend(["", "## 入口候选", ""])
    entry_points = [file for file in files if file.is_entry_point]
    if entry_points:
        report.extend(["| 文件 | 识别依据 |", "| --- | --- |"])
        for file in entry_points:
            reason = "文件名约定" if file.path.name in {"main.py", "app.py", "cli.py", "manage.py", "__main__.py"} else "包含 __name__ == __main__"
            report.append(f"| `{markdown_cell(file.path.relative_to(root).as_posix())}` | {reason} |")
    else:
        report.append("未识别到常见 Python 入口。")

    report.extend(["", "## Python 依赖概览", ""])
    if import_counts:
        report.extend(["| 被引用模块 | 引用次数 |", "| --- | ---: |"])
        for name, count in import_counts.most_common(15):
            report.append(f"| `{markdown_cell(name)}` | {count} |")
    else:
        report.append("当前没有检测到 Python import，或仓库中没有 Python 文件。")

    report.extend(["", "## Git 历史", ""])
    if not git.available:
        report.append("未检测到可用的 Git 历史。")
    else:
        report.extend([
            f"- 提交数：{git.commit_count}",
            f"- 贡献者数：{len(git.authors)}",
            "",
            "### 主要贡献者",
            "",
            "| 作者 | 提交数 |",
            "| --- | ---: |",
        ])
        for author, count in git.authors.most_common(10):
            report.append(f"| {markdown_cell(author)} | {count} |")
        report.extend(["", "### 最近提交", "", "| 提交 | 作者 | 日期 | 摘要 |", "| --- | --- | --- | --- |"])
        for commit, author, date, subject in git.recent_commits:
            report.append(f"| `{markdown_cell(commit)}` | {markdown_cell(author)} | {date} | {markdown_cell(subject)} |")
        report.extend(["", "### 高频修改路径", "", "| 路径 | 修改次数 |", "| --- | ---: |"])
        for path, count in git.changed_paths.most_common(15):
            report.append(f"| `{markdown_cell(path)}` | {count} |")

    report.extend(["", "## 文件清单", "", "| 文件 | 语言 | 非空行 |", "| --- | --- | ---: |"])
    for file in sorted(files, key=lambda item: (item.non_empty_lines, str(item.path)), reverse=True):
        relative = file.path.relative_to(root).as_posix()
        report.append(f"| `{markdown_cell(relative)}` | {markdown_cell(file.language)} | {file.non_empty_lines} |")
    return "\n".join(report) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """创建并配置命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="生成代码仓库的 Markdown 概览")
    parser.add_argument("root", nargs="?", default=".", help="待分析的仓库目录，默认当前目录")
    parser.add_argument("-o", "--output", default="REPOPATH_REPORT.md", help="报告输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数、执行仓库分析并写入报告文件。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"目录不存在：{root}")

    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    files = scan_files(root, {output})
    analysis = Analysis(root=root, files=files, git=collect_git_summary(root))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(analysis), encoding="utf-8")
    print(f"分析完成：扫描 {len(files)} 个文件，报告已写入 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
