"""命令行入口。"""

import argparse
import json
from pathlib import Path

from ..core.service import (
    analyze_repository,
    fetch_github_rate_limit,
)
from ..core.config import (
    AnalysisConfigError,
    ensure_default_config,
    load_analysis_options,
)
from ..model.options import AnalysisOptions
from ..model.repository import Repository, RepositorySource
from ..provider.github import GitHubRepositoryRef
from ..renderer.json import JsonRenderer
from ..renderer.markdown import MarkdownRenderer


def build_parser() -> argparse.ArgumentParser:
    """创建并配置命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="生成代码仓库的 Markdown 概览"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="待分析的本地目录或 GitHub 公开仓库地址，默认当前目录",
    )
    parser.add_argument(
        "--ref",
        help="GitHub 分支、标签或提交 SHA，默认使用仓库默认分支",
    )
    parser.add_argument(
        "--rate-limit",
        action="store_true",
        help="仅输出当前 GitHub Core API 限额，不读取仓库或生成报告",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="REPOPATH_REPORT.md",
        help="报告输出路径",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("markdown", "json"),
        default=None,
        help="报告格式，默认根据输出扩展名判断",
    )
    parser.add_argument(
        "-d",
        "--detail",
        choices=("summary", "full"),
        default="summary",
        help="Markdown 详情级别，默认摘要；JSON 始终输出完整结构",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="detail",
        action="store_const",
        const="full",
        default=argparse.SUPPRESS,
        help="输出完整 Markdown，等同于 --detail full",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="配置文件路径，默认读取仓库根目录 .repopath.toml",
    )
    parser.add_argument(
        "-p",
        "--profile",
        choices=("fast", "standard", "deep"),
        help="分析模式",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        action="append",
        default=[],
        help="追加排除路径模式，可重复使用",
    )
    parser.add_argument(
        "-m",
        "--max-file-size",
        type=int,
        help="可读取文本文件的最大字节数",
    )
    parser.add_argument(
        "-g",
        "--git-period",
        choices=("all", "30", "90"),
        help="Git 历史时间范围",
    )
    parser.add_argument(
        "-n",
        "--result-limit",
        type=int,
        help="Markdown 报告每类列表最大数量",
    )
    parser.add_argument(
        "-l",
        "--reading-limit",
        type=int,
        help="推荐阅读和评分明细最大数量",
    )
    parser.add_argument(
        "--github-limits",
        action="append",
        metavar="KEY=VALUE",
        help=(
            "GitHub 快照限制，可重复设置："
            "archive_mb、files、content_mb、file_mb"
        ),
    )
    parser.add_argument(
        "-i",
        "--include-file-list",
        dest="include_file_list",
        action="store_true",
        default=None,
        help="在 Markdown 报告中包含文件清单",
    )
    parser.add_argument(
        "--no-python",
        dest="python_enabled",
        action="store_false",
        default=None,
        help="关闭 Python Analyzer",
    )
    parser.add_argument(
        "--no-cpp",
        dest="cpp_enabled",
        action="store_false",
        default=None,
        help="关闭 C++ Analyzer",
    )
    parser.add_argument(
        "--no-git",
        dest="git_enabled",
        action="store_false",
        default=None,
        help="关闭 Git Analyzer",
    )
    parser.add_argument(
        "--no-dependencies",
        dest="dependencies_enabled",
        action="store_false",
        default=None,
        help="关闭统一依赖图",
    )
    parser.add_argument(
        "--no-insights",
        dest="insights_enabled",
        action="store_false",
        default=None,
        help="关闭评分和阅读路线",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析参数、运行 Pipeline 并输出 Markdown 报告。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rate_limit:
        rate_limit = fetch_github_rate_limit()
        print(
            json.dumps(
                {
                    "limit": rate_limit.limit,
                    "remaining": rate_limit.remaining,
                    "reset": rate_limit.reset,
                },
                ensure_ascii=False,
            )
        )
        return 0
    source, config_root, local_repository = _resolve_source(
        args.root, args.ref, parser
    )

    output = Path(args.output)
    if not output.is_absolute():
        output = config_root / output
    output = output.resolve()
    output_format = args.format or (
        "json" if output.suffix.lower() == ".json" else "markdown"
    )
    if args.format == "json" and args.output == "REPOPATH_REPORT.md":
        output = config_root / "REPOPATH_REPORT.json"
    try:
        if args.config is None:
            ensure_default_config(config_root)
        github_limits = _parse_github_limits(args.github_limits)
        options = _resolve_options(
            config_root, args, github_limits=github_limits
        )
    except AnalysisConfigError as exc:
        parser.error(str(exc))
    excluded_paths = {output} if local_repository is not None else None
    report = analyze_repository(source, excluded_paths, options=options)
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer = (
        JsonRenderer()
        if output_format == "json"
        else MarkdownRenderer()
    )
    if isinstance(renderer, MarkdownRenderer):
        content = renderer.render(report, detail=args.detail)
    else:
        content = renderer.render(report)
    output.write_text(content, encoding="utf-8")
    print(f"分析完成：扫描 {len(report.files)} 个文件")
    print(f"分析模式：{options.profile}；报告已写入 {output}")
    if not options.dependencies_enabled or not options.git_enabled:
        print(
            "提示：当前模式未启用完整导航；需要依赖、阅读路线和 Git "
            "热点时使用 --profile deep。"
        )
    return 0


def _resolve_source(
    value: str,
    reference: str | None,
    parser: argparse.ArgumentParser,
) -> tuple[Path | RepositorySource, Path, Repository | None]:
    """识别本地目录或 GitHub 地址并确定配置与输出目录。"""
    if _looks_like_github_location(value):
        try:
            github = GitHubRepositoryRef.parse(value)
        except ValueError as exc:
            parser.error(str(exc))
        return (
            RepositorySource.github(github.location, reference),
            Path.cwd().resolve(),
            None,
        )
    if reference is not None:
        parser.error("--ref 仅支持 GitHub 公开仓库来源")
    try:
        repository = Repository.from_path(value)
    except NotADirectoryError as exc:
        parser.error(str(exc))
    return repository.root, repository.root, repository


def _looks_like_github_location(value: str) -> bool:
    """判断输入是否意图表示 GitHub 网页仓库地址。"""
    candidate = value.strip().lower()
    if candidate.startswith("github.com/") or candidate.startswith(
        "https://github.com/"
    ):
        return True
    if (
        not candidate
        or "://" in candidate
        or candidate.startswith((".", "/", "~"))
        or Path(value).expanduser().is_dir()
    ):
        return False
    parts = candidate.split("/")
    return len(parts) == 2 and all(parts)


def _resolve_options(
    root: Path,
    args: argparse.Namespace,
    *,
    github_limits: dict[str, int] | None = None,
) -> AnalysisOptions:
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
    effective_python = (
        options.python_enabled
        if python_enabled is None
        else python_enabled
    )
    effective_cpp = (
        options.cpp_enabled if cpp_enabled is None else cpp_enabled
    )
    if dependencies_enabled is False or (
        not effective_python and not effective_cpp
    ):
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
            **(github_limits or {}),
        )
    except ValueError as exc:
        raise AnalysisConfigError(str(exc)) from exc


def _parse_github_limits(
    values: list[str] | None,
) -> dict[str, int]:
    """解析 CLI 的 GitHub 快照限制键值参数。"""
    if not values:
        return {}
    keys = {
        "archive_mb": "github_archive_max_bytes",
        "files": "github_file_limit",
        "content_mb": "github_content_max_bytes",
        "file_mb": "github_file_max_bytes",
    }
    parsed: dict[str, int] = {}
    for item in values:
        key, separator, raw = item.partition("=")
        if not separator or key not in keys:
            raise AnalysisConfigError(
                "--github-limits 必须使用 archive_mb/files/content_mb/file_mb=数值"
            )
        try:
            number = int(raw)
        except ValueError as exc:
            raise AnalysisConfigError(
                f"GitHub 快照限制 {key} 必须是整数"
            ) from exc
        if number <= 0:
            raise AnalysisConfigError("GitHub 快照限制必须大于 0")
        parsed[keys[key]] = (
            number * 1024 * 1024 if key.endswith("_mb") else number
        )
    return parsed
