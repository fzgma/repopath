"""Markdown 报告 Renderer。"""

import re
from collections import Counter
from html import escape

from ..model.file import FILE_STATISTICS_SCOPE, FileRecord
from ..model.report import RepositoryReport
from ..model.result import AnalyzerName, AnalyzerStatus
from .reading import (
    CONFIDENCE_LABELS,
    EVIDENCE_LABELS,
    GAP_LABELS,
    KIND_LABELS,
    READING_BOUNDARY,
    READING_STEP_LIMIT,
    format_location,
    reading_detail_limit,
    reading_state,
    unique_preview_locations,
)


def markdown_cell(value: object) -> str:
    """转义 Markdown 表格单元格中的特殊字符。"""
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_row(*cells: object) -> str:
    """将已转义的单元格组合为 Markdown 表格行。"""
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _file_sort_key(file: FileRecord) -> tuple[int, str]:
    """返回 Markdown 文件清单的稳定排序键。"""
    return file.non_empty_lines, str(file.path)


def _markdown_cycle_member(node: str) -> str:
    """将循环成员格式化为 Markdown 嵌套列表项。"""
    return f"  - `{markdown_cell(node)}`"


def _cpp_conditions(conditions: tuple[str, ...]) -> str:
    """用括号区分嵌套条件，保留每层表达式原有的运算顺序。"""
    return " && ".join(f"({condition})" for condition in conditions) or "无"


def _reading_text(value: object) -> str:
    """将仓库提供的文本作为普通文字展示，避免改变 Markdown 结构。"""
    text = escape(" ".join(str(value).splitlines()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()|~])", r"\\\1", text)


def _reading_preview(excerpt: str) -> list[str]:
    """用长于内容中所有反引号的围栏保留代码原文。"""
    if not excerpt:
        return []
    longest = max((len(item) for item in re.findall(r"`+", excerpt)), default=0)
    fence = "`" * max(3, longest + 1)
    return ["", f"{fence}text\n{excerpt}\n{fence}", ""]


class MarkdownRenderer:
    """将 RepositoryReport 渲染为可阅读的 Markdown 文档。"""

    def render(
        self, report: RepositoryReport, *, detail: str = "full"
    ) -> str:
        """生成包含概览、分析结果、Git 历史和文件清单的 Markdown。"""
        if detail == "summary":
            return self._render_summary(report)
        if detail != "full":
            raise ValueError("Markdown 详情级别必须是 summary 或 full")
        repository = report.repository
        stats = report.stats
        python = report.python
        cpp = report.cpp
        git = report.git
        files = report.files
        lines = [
            f"# RepoPath 报告：`{markdown_cell(repository.name)}`",
            "",
            f"> 生成时间：{report.generated_at or self._timestamp()} · "
            f"RepoPath {report.tool_version} · Schema "
            f"{report.schema_version}",
            "",
            "## 概览",
            "",
            FILE_STATISTICS_SCOPE,
            "",
            f"- 文件数：{len(files)}",
            f"- 非空行数：{stats.total_non_empty_lines}",
            f"- 识别语言：{len(stats.language_counts)}",
            f"- Python 入口候选：{len(python.entry_points)}",
            f"- C++ 入口候选：{len(cpp.entry_points)}",
            f"- 注释行：{stats.total_comment_lines}",
            f"- 依赖节点：{len(report.dependencies.nodes)}",
            f"- 依赖边：{len(report.dependencies.edges)}",
            f"- 分析耗时：{report.elapsed_seconds:.3f} 秒",
        ]
        if report.source is not None:
            lines.append(
                f"- 仓库来源：{markdown_cell(report.source.location)}"
            )
            if report.source.reference:
                reference = markdown_cell(report.source.reference)
                lines.append(f"- 固定提交：`{reference}`")
        if report.github_rate_limit is not None:
            rate_limit = report.github_rate_limit
            lines.extend(
                [
                    f"- GitHub API 限额：{rate_limit.remaining} / "
                    f"{rate_limit.limit}",
                    "- GitHub API 重置："
                    f"{rate_limit.reset_at:%Y-%m-%d %H:%M:%S %z}",
                ]
            )
        if report.warnings or report.errors:
            lines.extend(["", "## 分析提示", ""])
            lines.extend(
                f"- 警告：{markdown_cell(message)}"
                for message in report.warnings
            )
            lines.extend(
                f"- 错误：{markdown_cell(message)}"
                for message in report.errors
            )
        self._append_analysis_hint(lines, report)
        self._append_reading_guide(lines, report)

        lines.extend(
            [
                "",
                "## 语言统计",
                "",
                "| 语言族 | 文件数 | 非空行 | 文件占比 |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for (
            language,
            count,
        ) in stats.language_family_counts.most_common():
            percentage = count / len(files) * 100 if files else 0
            lines.append(
                f"| {markdown_cell(language)} | {count} | "
                f"{stats.language_family_lines[language]} | "
                f"{percentage:.1f}% |"
            )

        lines.extend(
            [
                "",
                "## 主要目录",
                "",
                "| 目录 | 文件数 | 非空行 |",
                "| --- | ---: | ---: |",
            ]
        )
        for directory, count in stats.directory_counts.most_common(15):
            lines.append(
                f"| `{markdown_cell(directory)}` | {count} | "
                f"{stats.directory_lines[directory]} |"
            )

        lines.extend(
            [
                "",
                "## Python 核心模块候选",
                "",
                "> 按非空行数、本地引用次数和入口特征进行排序。",
                "",
                "| 模块 | 非空行 | 被引用 | 评分 |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        if python.core_modules:
            for module in python.core_modules[:15]:
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(module.name)}`",
                        module.lines,
                        module.references,
                        module.score,
                    )
                )
        else:
            lines.append("| 暂无 Python 模块 | 0 | 0 | 0 |")

        self._append_entries(lines, report)

        lines.extend(["", "## Python 依赖概览", ""])
        if python.import_counts:
            lines.extend(
                ["| 被引用模块 | 引用次数 |", "| --- | ---: |"]
            )
            for name, count in python.import_counts.most_common(15):
                lines.append(f"| `{markdown_cell(name)}` | {count} |")
        else:
            lines.append(
                "当前没有检测到 Python import，或仓库中没有 Python 文件。"
            )

        lines.extend(["", "## Python 本地模块依赖", ""])
        if python.dependencies:
            lines.extend(["| 来源模块 | 目标模块 |", "| --- | --- |"])
            for edge in python.dependencies:
                lines.append(
                    f"| `{markdown_cell(edge.source)}` | "
                    f"`{markdown_cell(edge.target)}` |"
                )
        else:
            lines.append("未检测到仓库内 Python 模块之间的直接依赖。")

        lines.extend(["", "## C++ 分析", ""])
        if cpp.files:
            lines.extend(
                [
                    f"- C++ 文件数：{len(cpp.files)}",
                    f"- 函数数：{cpp.function_count}",
                    f"- 类和结构体数：{cpp.type_count}",
                    f"- 命名空间数：{cpp.namespace_count}",
                    f"- 入口候选：{len(cpp.entry_points)}",
                    "",
                    "### 常用 Include",
                    "",
                    "| Include | 引用次数 |",
                    "| --- | ---: |",
                ]
            )
            for include, count in cpp.include_counts.most_common(15):
                lines.append(
                    f"| `{markdown_cell(include)}` | {count} |"
                )
            lines.extend(
                [
                    "",
                    "### C++ 入口候选",
                    "",
                    "| 文件 | 名称 | 行号 | 条件 |",
                    "| --- | --- | ---: | --- |",
                ]
            )
            for entry in cpp.entry_points:
                entry_path = repository.relative_path(entry.path)
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(entry_path)}`",
                        f"`{markdown_cell(entry.name)}`",
                        entry.line,
                        markdown_cell(_cpp_conditions(entry.conditions)),
                    )
                )
            lines.extend(
                [
                    "",
                    "### C++ 符号",
                    "",
                    "| 文件 | 名称 | 类型 | 行号 |",
                    "| --- | --- | --- | ---: |",
                ]
            )
            for path, item in cpp.files.items():
                for symbol in [
                    *item.functions,
                    *item.types,
                    *item.namespaces,
                ]:
                    symbol_path = repository.relative_path(path)
                    lines.append(
                        markdown_row(
                            f"`{markdown_cell(symbol_path)}`",
                            f"`{markdown_cell(symbol.name)}`",
                            symbol.kind,
                            symbol.line,
                        )
                    )
            self._append_cpp_includes(lines, report, report.options.result_limit)
        else:
            lines.append("当前没有检测到 C++ 源文件或头文件。")

        graph = report.dependencies
        limit = report.options.result_limit
        reading_limit = report.options.reading_limit
        lines.extend(["", "## 统一依赖图", ""])
        if graph.nodes:
            lines.extend(
                [
                    f"- 节点数：{len(graph.nodes)}",
                    f"- 依赖边数：{len(graph.edges)}",
                    f"- 目录节点数：{len(graph.directory_nodes)}",
                    f"- 循环依赖数：{len(graph.cycles)}",
                    f"- 孤立节点数：{len(graph.isolated_nodes)}",
                    "",
                    "### 依赖边",
                    "",
                    "| 来源 | 目标 | 类型 |",
                    "| --- | --- | --- |",
                ]
            )
            for edge in graph.edges[:limit]:
                lines.append(
                    f"| `{markdown_cell(edge.source)}` | "
                    f"`{markdown_cell(edge.target)}` | {edge.kind} |"
                )
            lines.extend(["", "### 循环依赖", ""])
            if graph.cycles:
                for index, cycle in enumerate(
                    graph.cycles[:limit], start=1
                ):
                    lines.append(
                        "- 循环成员（强连通组 "
                        f"{index}，{len(cycle)} 个模块）："
                    )
                    members = [
                        _markdown_cycle_member(node) for node in cycle
                    ]
                    lines.extend(members)
            else:
                lines.append("未检测到循环依赖。")
            lines.extend(["", "### 孤立模块", ""])
            if graph.isolated_nodes:
                lines.extend(
                    f"- `{markdown_cell(node)}`"
                    for node in graph.isolated_nodes[:limit]
                )
            else:
                lines.append("未检测到孤立模块。")
        else:
            lines.append("分析已完成，未发现可构建依赖图的模块。")

        insights = report.insights
        lines.extend(["", "## 推荐阅读顺序", ""])
        if insights.reading_order:
            lines.extend(
                [
                    "| 排名 | 文件 | 语言 | 阅读优先级 | 入口距离 | 推荐原因 |",
                    "| ---: | --- | --- | ---: | ---: | --- |",
                ]
            )
            for item in insights.reading_order[:reading_limit]:
                distance = (
                    item.entry_distance
                    if item.entry_distance is not None
                    else "不可达"
                )
                lines.append(
                    markdown_row(
                        item.rank,
                        f"`{markdown_cell(item.path)}`",
                        item.language,
                        f"{item.reading_priority_score:.2f}",
                        distance,
                        markdown_cell("；".join(item.reasons)),
                    )
                )
        else:
            lines.append("分析已完成，没有可推荐阅读的模块。")

        lines.extend(
            [
                "",
                "## 模块评分",
                "",
                "> 阅读优先级由规模、依赖和入口组成；变更关注度由依赖暴露和 Git 活跃度组成。",
                "",
            ]
        )
        if insights.module_scores:
            lines.extend(
                [
                    "| 文件 | 规模 | 依赖 | 入口 | Git | 阅读优先级 | 变更关注度 |",
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for item in sorted(
                insights.module_scores,
                key=lambda score: (
                    -score.reading_priority_score,
                    score.path,
                ),
            )[:reading_limit]:
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(item.path)}`",
                        f"{item.size_score:.2f}",
                        f"{item.dependency_score:.2f}",
                        f"{item.entry_score:.2f}",
                        f"{item.git_score:.2f}" if item.git_score is not None else "未计算",
                        f"{item.reading_priority_score:.2f}",
                        f"{item.change_attention_score:.2f}"
                        if item.change_attention_score is not None else "未计算",
                    )
                )
        else:
            lines.append("暂无核心模块评分。")

        lines.extend(
            [
                "",
                "## 变更关注模块",
                "",
                "> 变更关注度由依赖暴露和 Git 活跃度组成，不代表缺陷概率。",
                "",
            ]
        )
        if insights.change_attention:
            lines.extend(
                [
                    "| 文件 | 语言 | 依赖分 | 修改次数 | 变更关注度 |",
                    "| --- | --- | ---: | ---: | ---: |",
                ]
            )
            for item in insights.change_attention[:limit]:
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(item.path)}`",
                        item.language,
                        f"{item.dependency_score:.2f}",
                        item.git_changes,
                        f"{item.change_attention_score:.2f}",
                    )
                )
        else:
            lines.append(
                "未检测到同时具有依赖暴露和 Git 活跃度的文件。"
            )

        lines.extend(["", "## Git 历史", ""])
        if not git.available:
            lines.append("未检测到可用的 Git 历史。")
        else:
            lines.extend(
                [
                    f"- 提交数：{git.commit_count}",
                    f"- 贡献者数：{len(git.authors)}",
                    f"- 首次提交：{git.first_commit_date or '未知'}",
                    f"- 最近提交：{git.last_commit_date or '未知'}",
                    f"- 浅克隆：{'是' if git.shallow else '否'}",
                    "",
                    "### 主要贡献者",
                    "",
                    "| 作者 | 提交数 |",
                    "| --- | ---: |",
                ]
            )
            for author, count in git.authors.most_common(10):
                lines.append(f"| {markdown_cell(author)} | {count} |")
            lines.extend(
                [
                    "",
                    "### 最近提交",
                    "",
                    "| 提交 | 作者 | 日期 | 摘要 |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for commit in git.recent_commits:
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(commit.identifier)}`",
                        markdown_cell(commit.author),
                        commit.date,
                        markdown_cell(commit.subject),
                    )
                )
            lines.extend(
                [
                    "",
                    "### 高频修改路径",
                    "",
                    "| 路径 | 修改次数 |",
                    "| --- | ---: |",
                ]
            )
            for path, count in git.changed_paths.most_common(15):
                lines.append(f"| `{markdown_cell(path)}` | {count} |")
            lines.extend(
                [
                    "",
                    "### 提交趋势",
                    "",
                    "| 月份 | 提交数 |",
                    "| --- | ---: |",
                ]
            )
            for month, count in sorted(git.commits_by_month.items()):
                lines.append(f"| `{markdown_cell(month)}` | {count} |")
            lines.extend(
                [
                    "",
                    "### 月度代码变化",
                    "",
                    "| 月份 | 提交 | 新增 | 删除 |",
                    "| --- | ---: | ---: | ---: |",
                ]
            )
            for month, change in sorted(git.monthly_changes.items()):
                lines.append(
                    markdown_row(
                        f"`{month}`",
                        change.commits,
                        change.additions,
                        change.deletions,
                    )
                )
            lines.extend(
                [
                    "",
                    "### 文件变更热点",
                    "",
                    "| 文件 | 提交 | 文件新增 | 文件删除 | 文件修改 | "
                    "新增行 | 删除行 | Churn |",
                    "| --- | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: |",
                ]
            )
            hottest = sorted(
                git.file_changes.items(),
                key=lambda item: (-item[1].churn, item[0]),
            )
            for path, change in hottest[:limit]:
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(path)}`",
                        change.commits,
                        change.added,
                        change.deleted,
                        change.modified,
                        change.additions,
                        change.deletions,
                        change.churn,
                    )
                )
            lines.extend(
                [
                    "",
                    "### 共同修改文件",
                    "",
                    "| 文件 A | 文件 B | 次数 |",
                    "| --- | --- | ---: |",
                ]
            )
            for (left, right), count in git.co_changes.most_common(
                limit
            ):
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(left)}`",
                        f"`{markdown_cell(right)}`",
                        count,
                    )
                )
            lines.extend(
                [
                    "",
                    "### 目录贡献者",
                    "",
                    "| 目录 | 主要贡献者 | 文件变更 |",
                    "| --- | --- | ---: |",
                ]
            )
            for directory, authors in sorted(
                git.directory_authors.items()
            ):
                if authors:
                    author, count = authors.most_common(1)[0]
                    lines.append(
                        markdown_row(
                            f"`{markdown_cell(directory)}`",
                            markdown_cell(author),
                            count,
                        )
                    )
            lines.extend(["", "### 活跃与稳定文件", ""])
            lines.append(
                f"- 最近 90 天活跃：{len(git.active_paths)} 个"
            )
            lines.append(
                f"- 超过 90 天未修改：{len(git.stable_paths)} 个"
            )

        lines.extend(
            [
                "",
                "## Analyzer 耗时",
                "",
                "| Analyzer | 秒 |",
                "| --- | ---: |",
            ]
        )
        for name, duration in report.analyzer_durations.items():
            lines.append(
                f"| `{markdown_cell(name)}` | {duration:.6f} |"
            )

        if report.options.include_file_list:
            lines.extend(
                [
                    "",
                    "## 文件清单",
                    "",
                    "| 文件 | 语言 | 非空行 |",
                    "| --- | --- | ---: |",
                ]
            )
            for file in sorted(
                files,
                key=_file_sort_key,
                reverse=True,
            ):
                file_path = repository.relative_path(file.path)
                lines.append(
                    markdown_row(
                        f"`{markdown_cell(file_path)}`",
                        markdown_cell(file.language),
                        file.non_empty_lines,
                    )
                )
        return self._with_status(lines, report)

    def _render_summary(self, report: RepositoryReport) -> str:
        """生成适合人工快速阅读的精简 Markdown 摘要。"""
        repository = report.repository
        stats = report.stats
        graph = report.dependencies
        insights = report.insights
        lines = [
            f"# RepoPath 摘要：`{markdown_cell(repository.name)}`",
            "",
            f"> 生成时间：{report.generated_at or self._timestamp()} · "
            f"RepoPath {report.tool_version}",
            "",
            "## 概览",
            "",
            FILE_STATISTICS_SCOPE,
            "",
            f"- 文件数：{len(report.files)}",
            f"- 非空行数：{stats.total_non_empty_lines}",
            f"- 识别语言：{len(stats.language_counts)}",
            f"- 分析模式：{report.options.profile}",
            f"- 已启用 Analyzer：{self._enabled_analyzers(report)}",
            f"- Python 入口候选：{len(report.python.entry_points)}",
            f"- C++ 入口候选：{len(report.cpp.entry_points)}",
            f"- 依赖节点：{len(graph.nodes)}",
            f"- 依赖边：{len(graph.edges)}",
            f"- 分析耗时：{report.elapsed_seconds:.3f} 秒",
        ]
        if report.source is not None:
            lines.append(
                f"- 仓库来源：{markdown_cell(report.source.location)}"
            )
            if report.source.reference:
                reference = markdown_cell(report.source.reference)
                lines.append(f"- 固定提交：`{reference}`")
        self._append_summary_messages(lines, report)
        self._append_analysis_hint(lines, report)
        self._append_reading_guide(lines, report, detail="summary")

        lines.extend(["", "## Python 核心模块", ""])
        if report.python.core_modules:
            lines.extend(
                f"- `{markdown_cell(module.name)}`："
                f"{module.lines} 行，引用 {module.references} 次，"
                f"评分 {module.score}"
                for module in report.python.core_modules[:10]
            )
        else:
            lines.append("暂无 Python 核心模块候选。")

        self._append_entries(lines, report, limit=10)
        if report.cpp.files:
            self._append_cpp_includes(
                lines, report, limit=min(5, report.options.result_limit)
            )

        lines.extend(["", "## 推荐阅读", ""])
        if insights.reading_order:
            for item in insights.reading_order[:10]:
                lines.append(
                    f"{item.rank}. `{markdown_cell(item.path)}`："
                    f"{markdown_cell('；'.join(item.reasons))}"
                )
        else:
            lines.append("分析已完成，没有可推荐阅读的模块。")

        if insights.reading_paths:
            lines.extend(["", "### 入口到推荐模块的路径", ""])
            for item in insights.reading_paths[:10]:
                lines.append(
                    f"- `{markdown_cell(item.entry)}` -> "
                    f"`{markdown_cell(item.target)}`："
                    f"`{markdown_cell(' -> '.join(item.nodes))}`"
                )

        lines.extend(["", "## 变更关注模块", ""])
        if insights.change_attention:
            for item in insights.change_attention[:10]:
                lines.append(
                    f"- `{markdown_cell(item.path)}`："
                    f"依赖分 {item.dependency_score:.2f}，"
                    f"Git 修改 {item.git_changes} 次，"
                    f"变更关注度 {item.change_attention_score:.2f}"
                )
        else:
            lines.append("未检测到变更关注模块。")

        lines.extend(["", "## 循环依赖", ""])
        if graph.cycles:
            for index, cycle in enumerate(graph.cycles[:10], start=1):
                members = "、".join(
                    f"`{markdown_cell(node)}`" for node in cycle[:10]
                )
                lines.append(f"- 循环组 {index}：{members}")
        else:
            lines.append("未检测到循环依赖。")

        if report.git.available:
            lines.extend(["", "## Git 变更热点", ""])
            hottest = sorted(
                report.git.file_changes.items(),
                key=lambda item: (-item[1].churn, item[0]),
            )
            for path, change in hottest[:10]:
                lines.append(
                    f"- `{markdown_cell(path)}`："
                    f"Churn {change.churn}，提交 {change.commits} 次"
                )
        return self._with_status(lines, report)

    @staticmethod
    def _append_reading_guide(
        lines: list[str], report: RepositoryReport, *, detail: str = "full",
    ) -> None:
        """摘要先列阅读线索，完整报告再展开证据与去重后的片段。"""
        guide = report.reading_guide
        result = report.analyzer_result(AnalyzerName.READING)
        limit = reading_detail_limit(report)
        lines.extend([
            "", "## 阅读指南（实验）", "",
            READING_BOUNDARY, "",
            f"状态：`{result.status}` · {len(guide.steps)} 条线索"
            + (" · 已截断" if guide.truncated else ""),
        ])
        if result.reason:
            lines.append(f"- 原因：{_reading_text(result.reason)}")
        if not result.successful or not guide.steps or guide.gaps or guide.truncated:
            lines.extend(["", reading_state(report)])
        for label, messages in (("警告", result.warnings), ("错误", result.errors)):
            for message in messages[:limit]:
                lines.append(f"- {label}：{_reading_text(message)}")
            MarkdownRenderer._append_reading_omission(lines, len(messages), limit, label)
        if result.status == AnalyzerStatus.NOT_RUN:
            return
        lines.extend(["", "### 1. 项目说明摘录", ""])
        for item in guide.purpose:
            lines.append(f"- 原文摘录：{_reading_text(item.description)}（{_reading_text(format_location(item.location))}）")
        if not guide.purpose:
            lines.append("未提取到项目说明片段。")
        lines.extend(["", "### 2. 组成线索", ""])
        for item in guide.structure:
            lines.append(f"- 原文摘录：{_reading_text(item.description)}（{_reading_text(format_location(item.location))}）")
        if guide.components:
            lines.extend(["", "| 路径 | 说明摘录或结构记录 | 来源 |", "| --- | --- | --- |"])
            for item in guide.components:
                lines.append(markdown_row(
                    _reading_text(item.path), _reading_text(item.summary),
                    _reading_text(format_location(item.location)),
                ))
        elif not guide.structure:
            lines.append("未提取到组成说明或目录、包边界。")
        lines.extend(["", "### 3. 阅读线索", ""])
        if detail == "summary":
            if guide.steps:
                lines.extend([
                    "| 位置 | 内容 | 列出依据 | 可核对内容 |",
                    "| --- | --- | --- | --- |",
                ])
            for step in guide.steps[:READING_STEP_LIMIT]:
                confidence = CONFIDENCE_LABELS.get(step.confidence, step.confidence)
                kind = KIND_LABELS.get(step.kind, step.kind)
                lines.append(markdown_row(
                    _reading_text(format_location(step.location)),
                    _reading_text(step.summary),
                    _reading_text(step.reason or f"{kind} · {confidence}"),
                    _reading_text(step.learn or step.question),
                ))
            MarkdownRenderer._append_reading_omission(lines, len(guide.steps), READING_STEP_LIMIT, "线索")
            if guide.gaps:
                counts = Counter(GAP_LABELS.get(gap.kind, gap.kind) for gap in guide.gaps)
                labels = [f"{kind} ×{count}" for kind, count in counts.items()]
                lines.extend(["", "限制：" + _reading_text("；".join(labels[:limit])) + "。"])
                MarkdownRenderer._append_reading_omission(lines, len(labels), limit, "限制类别")
            lines.extend([
                "", "来源、片段和限制详情：CLI 使用 `--detail full`，UI 展开“依据与片段”和“分析说明”。JSON 保存本次保留的线索与依据。",
            ])
            return
        for index, step in enumerate(guide.steps[:READING_STEP_LIMIT], start=1):
            confidence = CONFIDENCE_LABELS.get(step.confidence, step.confidence)
            kind = KIND_LABELS.get(step.kind, step.kind)
            lines.extend([
                "", f"### 线索 {index}：{_reading_text(step.question)}", "",
                f"{_reading_text(step.summary)}（{_reading_text(kind)} · {_reading_text(confidence)}）",
                "",
                f"- 位置：{_reading_text(format_location(step.location))}",
                f"- 主题：{_reading_text(step.topic)}",
            ])
            if step.reason:
                lines.append(f"- 列出依据：{_reading_text(step.reason)}")
            if step.learn:
                lines.append(f"- 可核对内容：{_reading_text(step.learn)}")
            if not step.evidence:
                lines.append("- 没有附带证据记录，需返回原文核对。")
            for evidence in step.evidence[:limit]:
                kind = EVIDENCE_LABELS.get(evidence.kind, evidence.kind)
                lines.append(
                    f"- 依据（{_reading_text(kind)}）：{_reading_text(evidence.description)}"
                    f"（{_reading_text(format_location(evidence.location))}）"
                )
            MarkdownRenderer._append_reading_omission(lines, len(step.evidence), limit, "证据")
            if step.related:
                for location in step.related[:limit]:
                    lines.append(f"- 关联候选：{_reading_text(format_location(location))}")
                MarkdownRenderer._append_reading_omission(lines, len(step.related), limit, "关联位置")
            for location in unique_preview_locations(step, limit):
                lines.extend(["", f"片段：{_reading_text(format_location(location))}"])
                lines.extend(_reading_preview(location.excerpt))
        MarkdownRenderer._append_reading_omission(lines, len(guide.steps), READING_STEP_LIMIT, "线索")
        lines.extend([
            "", "### 分析说明", "",
            f"扫描 {guide.scanned_files} 个文件，{guide.candidate_count} 个候选。",
        ])
        if guide.truncated:
            lines.append("已截断；JSON 不包含未入选候选、超预算关联或未分析内容。")
        for capability in guide.capabilities[:limit]:
            lines.append(f"- {_reading_text(capability)}")
        if not guide.capabilities:
            lines.append("没有能力范围记录。")
        MarkdownRenderer._append_reading_omission(lines, len(guide.capabilities), limit, "能力记录")
        for gap in guide.gaps[:limit]:
            kind = GAP_LABELS.get(gap.kind, gap.kind)
            path = f"（{_reading_text(gap.path)}）" if gap.path else ""
            lines.append(f"- {_reading_text(kind)}：{_reading_text(gap.message)}{path}")
        MarkdownRenderer._append_reading_omission(lines, len(guide.gaps), limit, "缺口")

    @staticmethod
    def _append_reading_omission(
        lines: list[str], count: int, limit: int, label: str,
    ) -> None:
        """区分展示省略与分析阶段未采集到的内容。"""
        if count > limit:
            lines.extend(["", f"其余 {count - limit} 条{label}在此省略；本列表的全部条目见 JSON 的 reading_guide。"])

    @staticmethod
    def _append_entries(
        lines: list[str], report: RepositoryReport, limit: int | None = None
    ) -> None:
        """分别说明两种语言的执行状态，只对已完成分析报告空入口。"""
        lines.extend(["", "## 入口候选", ""])
        for name, label, entries in (
            (AnalyzerName.PYTHON, "Python", [
                (entry.path, entry.reason) for entry in report.python.entry_points
            ]),
            (AnalyzerName.CPP, "C++", [
                (
                    entry.path,
                    f"C++ {entry.name}；条件："
                    + _cpp_conditions(entry.conditions),
                )
                for entry in report.cpp.entry_points
            ]),
        ):
            result = report.analyzer_result(name)
            lines.extend(["", f"### {label}", "", f"- 分析状态：`{result.status}`"])
            if result.reason:
                lines.append(f"- 原因：{markdown_cell(result.reason)}")
            if not result.successful:
                continue
            if not entries:
                lines.append(f"未识别到 {label} 入口候选。")
            for path, reason in entries[:limit]:
                lines.append(
                    f"- `{markdown_cell(report.repository.relative_path(path))}`："
                    f"{markdown_cell(reason)}"
                )

    @staticmethod
    def _append_cpp_includes(
        lines: list[str], report: RepositoryReport, limit: int
    ) -> None:
        """展示 include 路径证据，并保留未匹配项和互斥分支。"""
        details = [
            (report.repository.relative_path(path), include)
            for path, item in report.cpp.files.items()
            for include in item.include_details
        ]
        matched = sum(include.target is not None for _, include in details)
        ambiguous = sum(
            include.resolution == "ambiguous" for _, include in details
        )
        lines.extend([
            "", "### C++ Include 路径匹配", "",
            (
                f"- 共 {len(details)} 处；匹配 {matched} 处；"
                f"多个候选 {ambiguous} 处；"
                f"未匹配或宏形式 {len(details) - matched - ambiguous} 处。"
            ),
            (
                "- 依赖图汇总源码各分支的路径匹配结果，条件不求值；"
                "不表示某次构建的实际依赖或函数调用关系。"
            ),
            (
                "- 多个候选、未匹配和宏形式不计入依赖图。"
                "未匹配项可能来自外部库、生成文件或未扫描文件。"
            ),
            "", "| 位置 | Include | 匹配方式 | 目标或候选 | 条件 |",
            "| --- | --- | --- | --- | --- |",
        ])
        labels = {
            "relative": "相对当前文件", "repository": "仓库路径",
            "suffix": "路径后缀", "ambiguous": "多个候选",
            "unresolved": "未匹配", "macro": "宏形式",
        }
        for source, include in details[:limit]:
            targets = (
                [include.target] if include.target is not None
                else include.candidates
            )
            target_text = "、".join(
                report.repository.relative_path(path) for path in targets
            ) or "—"
            lines.append(markdown_row(
                f"`{markdown_cell(source)}:{include.line}`",
                f"`{markdown_cell(include.name)}`",
                labels[include.resolution],
                markdown_cell(target_text),
                markdown_cell(_cpp_conditions(include.conditions)),
            ))
        if len(details) > limit:
            lines.extend(["", f"其余 {len(details) - limit} 处省略；JSON 保留全部记录。"])

    @staticmethod
    def _with_status(lines: list[str], report: RepositoryReport) -> str:
        """在分析章节旁显示执行证据，避免把缺失结果描述为零结果。"""
        sections = {
            "Python 核心模块候选": AnalyzerName.PYTHON,
            "Python 核心模块": AnalyzerName.PYTHON,
            "Python 依赖概览": AnalyzerName.PYTHON,
            "Python 本地模块依赖": AnalyzerName.PYTHON,
            "C++ 分析": AnalyzerName.CPP,
            "统一依赖图": AnalyzerName.DEPENDENCIES,
            "循环依赖": AnalyzerName.DEPENDENCIES,
            "推荐阅读顺序": AnalyzerName.INSIGHTS,
            "推荐阅读": AnalyzerName.INSIGHTS,
            "模块评分": AnalyzerName.INSIGHTS,
            "变更关注模块": AnalyzerName.INSIGHTS,
            "Git 历史": AnalyzerName.GIT,
            "Git 变更热点": AnalyzerName.GIT,
            "语言统计": AnalyzerName.STATISTICS,
            "主要目录": AnalyzerName.STATISTICS,
            "文件清单": AnalyzerName.FILES,
        }
        labels = {AnalyzerStatus.NOT_RUN: "未运行", AnalyzerStatus.COMPLETED: "已完成",
                  AnalyzerStatus.FAILED: "失败"}
        metrics = {
            "- 文件数": AnalyzerName.FILES,
            "- 非空行数": AnalyzerName.STATISTICS,
            "- 识别语言": AnalyzerName.STATISTICS,
            "- 注释行": AnalyzerName.STATISTICS,
            "- Python 入口候选": AnalyzerName.PYTHON,
            "- C++ 入口候选": AnalyzerName.CPP,
            "- 依赖节点": AnalyzerName.DEPENDENCIES,
            "- 依赖边": AnalyzerName.DEPENDENCIES,
        }
        output: list[str] = []
        omit = False
        for line in lines:
            if line.startswith("## "):
                omit = False
                name = sections.get(line[3:])
                if name is not None:
                    result = (
                        report.change_attention_availability()
                        if line == "## 变更关注模块"
                        else report.analyzer_result(name)
                    )
                    if report.options.reading_enabled:
                        line = {
                            "## 推荐阅读": "## 结构统计（旧排序）",
                            "## 推荐阅读顺序": "## 结构统计（旧排序）",
                            "## Python 核心模块": "## Python 规模与引用统计",
                            "## Python 核心模块候选": "## Python 规模与引用统计",
                            "## 模块评分": "## 结构指标评分",
                        }.get(line, line)
                    output.extend([line, "", f"- 分析状态：{labels[result.status]}（`{result.status}`）"])
                    if result.reason:
                        output.append(f"- 原因：{markdown_cell(result.reason)}")
                    output.append("")
                    omit = result.status != AnalyzerStatus.COMPLETED
                    continue
            if omit:
                continue
            metric = line.split("：", 1)[0]
            if metric in metrics:
                result = report.analyzer_result(metrics[metric])
                if result.status != AnalyzerStatus.COMPLETED:
                    line = metric + "：" + labels[result.status]
            output.append(line)
        return "\n".join(output) + "\n"

    @staticmethod
    def _append_summary_messages(
        lines: list[str], report: RepositoryReport
    ) -> None:
        """将摘要所需的警告和错误追加到报告内容。"""
        if not report.warnings and not report.errors:
            return
        lines.extend(["", "## 分析提示", ""])
        lines.extend(
            f"- 警告：{markdown_cell(message)}"
            for message in report.warnings[:10]
        )
        lines.extend(
            f"- 错误：{markdown_cell(message)}"
            for message in report.errors[:10]
        )

    @staticmethod
    def _append_analysis_hint(
        lines: list[str], report: RepositoryReport
    ) -> None:
        """说明未启用分析项的影响和命令行处理方式。"""
        options = report.options
        hints: list[str] = []
        if not options.dependencies_enabled:
            hints.append(
                "当前未启用依赖分析，因此不会生成依赖图、基于依赖的推荐阅读和变更关注模块；阅读指南可单独启用。"
            )
        if not options.git_enabled:
            hints.append(
                "当前未启用 Git 分析，因此不会生成 Git 变更热点。"
            )
        if hints:
            lines.extend(["", "## 分析范围提示", ""])
            lines.extend(f"- {hint}" for hint in hints)
            if options.profile != "deep":
                lines.append(
                    "- 如需完整导航和 Git 分析，请重新运行："
                    "`python -m repopath . --profile deep`。"
                )

    @staticmethod
    def _enabled_analyzers(report: RepositoryReport) -> str:
        """返回摘要中实际启用的 Analyzer 名称。"""
        names = ["files", "statistics"]
        options = report.options
        if options.python_enabled:
            names.append("python")
        if options.cpp_enabled:
            names.append("cpp")
        if options.git_enabled:
            names.append("git")
        if options.dependencies_enabled:
            names.append("dependencies")
        if options.insights_enabled:
            names.append("insights")
        if options.reading_enabled:
            names.append("reading")
        return ", ".join(names)

    @staticmethod
    def _timestamp() -> str:
        """返回带时区的当前时间字符串。"""
        from datetime import datetime

        timestamp = datetime.now().astimezone()
        return timestamp.isoformat(timespec="seconds")
