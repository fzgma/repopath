"""命令行入口。"""

import argparse
from pathlib import Path

from ..core.service import analyze_repository
from ..core.config import AnalysisConfigError, ensure_default_config, load_analysis_options
from ..model.options import AnalysisOptions
from ..model.repository import Repository
from ..renderer.json import JsonRenderer
from ..renderer.markdown import MarkdownRenderer


def build_parser() -> argparse.ArgumentParser:
    """创建并配置命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="生成代码仓库的 Markdown 概览")
    parser.add_argument("root", nargs="?", default=".", help="待分析的仓库目录，默认当前目录")
    parser.add_argument("-o", "--output", default="REPOPATH_REPORT.md", help="报告输出路径")
    parser.add_argument("--format", choices=("markdown", "json"), default=None, help="报告格式，默认根据输出扩展名判断")
    parser.add_argument("--config", help="配置文件路径，默认读取仓库根目录 .repopath.toml")
    parser.add_argument("--profile", choices=("fast", "standard", "deep"), help="分析模式")
    parser.add_argument("--exclude", action="append", default=[], help="追加排除路径模式，可重复使用")
    parser.add_argument("--max-file-size", type=int, help="可读取文本文件的最大字节数")
    parser.add_argument("--git-period", choices=("all", "30", "90"), help="Git 历史时间范围")
    parser.add_argument("--result-limit", type=int, help="Markdown 报告每类列表最大数量")
    parser.add_argument("--reading-limit", type=int, help="推荐阅读和评分明细最大数量")
    parser.add_argument("--include-file-list", dest="include_file_list", action="store_true", default=None, help="在 Markdown 报告中包含文件清单")
    parser.add_argument("--no-python", dest="python_enabled", action="store_false", default=None, help="关闭 Python Analyzer")
    parser.add_argument("--no-cpp", dest="cpp_enabled", action="store_false", default=None, help="关闭 C++ Analyzer")
    parser.add_argument("--no-git", dest="git_enabled", action="store_false", default=None, help="关闭 Git Analyzer")
    parser.add_argument("--no-dependencies", dest="dependencies_enabled", action="store_false", default=None, help="关闭统一依赖图")
    parser.add_argument("--no-insights", dest="insights_enabled", action="store_false", default=None, help="关闭评分和阅读路线")
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析参数、运行 Pipeline 并输出 Markdown 报告。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repository = Repository.from_path(args.root)
    except NotADirectoryError as exc:
        parser.error(str(exc))

    output = Path(args.output)
    if not output.is_absolute():
        output = repository.root / output
    output = output.resolve()
    output_format = args.format or ("json" if output.suffix.lower() == ".json" else "markdown")
    if args.format == "json" and args.output == "REPOPATH_REPORT.md":
        output = repository.root / "REPOPATH_REPORT.json"
    try:
        if args.config is None:
            ensure_default_config(repository.root)
        options = _resolve_options(repository.root, args)
    except AnalysisConfigError as exc:
        parser.error(str(exc))
    report = analyze_repository(repository.root, {output}, options=options)
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer = JsonRenderer() if output_format == "json" else MarkdownRenderer()
    output.write_text(renderer.render(report), encoding="utf-8")
    print(f"分析完成：扫描 {len(report.files)} 个文件，报告已写入 {output}")
    return 0


def _resolve_options(root: Path, args: argparse.Namespace) -> AnalysisOptions:
    """按默认值、配置文件和 CLI 参数顺序合并分析选项。"""
    options = load_analysis_options(root, args.config)
    if args.profile:
        preset = AnalysisOptions.for_profile(args.profile)
        options = options.with_overrides(
            profile=preset.profile,
            python_enabled=preset.python_enabled,
            cpp_enabled=preset.cpp_enabled,
            git_enabled=preset.git_enabled,
            dependencies_enabled=preset.dependencies_enabled,
            insights_enabled=preset.insights_enabled,
        )
    excluded_patterns = options.excluded_patterns + tuple(args.exclude)
    dependencies_enabled = args.dependencies_enabled
    insights_enabled = args.insights_enabled
    python_enabled = args.python_enabled
    cpp_enabled = args.cpp_enabled
    effective_python = options.python_enabled if python_enabled is None else python_enabled
    effective_cpp = options.cpp_enabled if cpp_enabled is None else cpp_enabled
    if dependencies_enabled is False or (not effective_python and not effective_cpp):
        dependencies_enabled = False
        if insights_enabled is None:
            insights_enabled = False
    try:
        return options.with_overrides(
            excluded_patterns=excluded_patterns,
            max_file_size=args.max_file_size,
            git_period=args.git_period,
            result_limit=args.result_limit,
            reading_limit=args.reading_limit,
            include_file_list=args.include_file_list,
            python_enabled=python_enabled,
            cpp_enabled=cpp_enabled,
            git_enabled=args.git_enabled,
            dependencies_enabled=dependencies_enabled,
            insights_enabled=insights_enabled,
        )
    except ValueError as exc:
        raise AnalysisConfigError(str(exc)) from exc
