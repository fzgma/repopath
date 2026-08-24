"""命令行入口。"""

import argparse
from pathlib import Path

from ..core.service import analyze_repository
from ..model.repository import Repository
from ..renderer.json import JsonRenderer
from ..renderer.markdown import MarkdownRenderer


def build_parser() -> argparse.ArgumentParser:
    """创建并配置命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="生成代码仓库的 Markdown 概览")
    parser.add_argument("root", nargs="?", default=".", help="待分析的仓库目录，默认当前目录")
    parser.add_argument("-o", "--output", default="REPOPATH_REPORT.md", help="报告输出路径")
    parser.add_argument("--format", choices=("markdown", "json"), default=None, help="报告格式，默认根据输出扩展名判断")
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
    report = analyze_repository(repository.root, {output})
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer = JsonRenderer() if output_format == "json" else MarkdownRenderer()
    output.write_text(renderer.render(report), encoding="utf-8")
    print(f"分析完成：扫描 {len(report.files)} 个文件，报告已写入 {output}")
    return 0
