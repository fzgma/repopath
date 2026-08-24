"""Markdown 报告 Renderer。"""

from ..model.report import RepositoryReport


def markdown_cell(value: object) -> str:
    """转义 Markdown 表格单元格中的特殊字符。"""
    return str(value).replace("|", "\\|").replace("\n", " ")


class MarkdownRenderer:
    """将 RepositoryReport 渲染为可阅读的 Markdown 文档。"""

    def render(self, report: RepositoryReport) -> str:
        """生成包含概览、分析结果、Git 历史和文件清单的 Markdown。"""
        repository = report.repository
        stats = report.stats
        python = report.python
        cpp = report.cpp
        git = report.git
        files = report.files
        lines = [
            f"# RepoPath 报告：`{markdown_cell(repository.name)}`",
            "",
            f"> 生成时间：{report.generated_at or self._timestamp()} · RepoPath {report.tool_version} · Schema {report.schema_version}",
            "",
            "## 概览",
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
        if report.warnings or report.errors:
            lines.extend(["", "## 分析提示", ""])
            lines.extend(f"- 警告：{markdown_cell(message)}" for message in report.warnings)
            lines.extend(f"- 错误：{markdown_cell(message)}" for message in report.errors)

        lines.extend(["", "## 语言统计", "", "| 语言族 | 文件数 | 非空行 | 文件占比 |", "| --- | ---: | ---: | ---: |"])
        for language, count in stats.language_family_counts.most_common():
            percentage = count / len(files) * 100 if files else 0
            lines.append(f"| {markdown_cell(language)} | {count} | {stats.language_family_lines[language]} | {percentage:.1f}% |")

        lines.extend(["", "## 主要目录", "", "| 目录 | 文件数 | 非空行 |", "| --- | ---: | ---: |"])
        for directory, count in stats.directory_counts.most_common(15):
            lines.append(f"| `{markdown_cell(directory)}` | {count} | {stats.directory_lines[directory]} |")

        lines.extend(["", "## Python 核心模块候选", "", "> 按非空行数、本地引用次数和入口特征进行排序。", "", "| 模块 | 非空行 | 被引用 | 评分 |", "| --- | ---: | ---: | ---: |"])
        if python.core_modules:
            for module in python.core_modules[:15]:
                lines.append(f"| `{markdown_cell(module.name)}` | {module.lines} | {module.references} | {module.score} |")
        else:
            lines.append("| 暂无 Python 模块 | 0 | 0 | 0 |")

        lines.extend(["", "## 入口候选", ""])
        if python.entry_points:
            lines.extend(["| 文件 | 识别依据 |", "| --- | --- |"])
            for entry in python.entry_points:
                lines.append(f"| `{markdown_cell(repository.relative_path(entry.path))}` | {markdown_cell(entry.reason)} |")
        else:
            lines.append("未识别到常见 Python 入口。")

        lines.extend(["", "## Python 依赖概览", ""])
        if python.import_counts:
            lines.extend(["| 被引用模块 | 引用次数 |", "| --- | ---: |"])
            for name, count in python.import_counts.most_common(15):
                lines.append(f"| `{markdown_cell(name)}` | {count} |")
        else:
            lines.append("当前没有检测到 Python import，或仓库中没有 Python 文件。")

        lines.extend(["", "## Python 本地模块依赖", ""])
        if python.dependencies:
            lines.extend(["| 来源模块 | 目标模块 |", "| --- | --- |"])
            for edge in python.dependencies:
                lines.append(f"| `{markdown_cell(edge.source)}` | `{markdown_cell(edge.target)}` |")
        else:
            lines.append("未检测到仓库内 Python 模块之间的直接依赖。")

        lines.extend(["", "## C++ 分析", ""])
        if cpp.files:
            lines.extend([
                f"- C++ 文件数：{len(cpp.files)}",
                f"- 函数数：{cpp.function_count}",
                f"- 类和结构体数：{cpp.type_count}",
                f"- 命名空间数：{cpp.namespace_count}",
                f"- main 入口候选：{len(cpp.entry_points)}",
                "",
                "### 常用 Include",
                "",
                "| Include | 引用次数 |",
                "| --- | ---: |",
            ])
            for include, count in cpp.include_counts.most_common(15):
                lines.append(f"| `{markdown_cell(include)}` | {count} |")
            lines.extend(["", "### C++ 入口候选", "", "| 文件 | 行号 |", "| --- | ---: |"])
            for entry in cpp.entry_points:
                lines.append(f"| `{markdown_cell(repository.relative_path(entry.path))}` | {entry.line} |")
            lines.extend(["", "### C++ 符号", "", "| 文件 | 名称 | 类型 | 行号 |", "| --- | --- | --- | ---: |"])
            for path, item in cpp.files.items():
                for symbol in [*item.functions, *item.types, *item.namespaces]:
                    lines.append(
                        f"| `{markdown_cell(repository.relative_path(path))}` | `{markdown_cell(symbol.name)}` | {symbol.kind} | {symbol.line} |"
                    )
            lines.extend(["", "### 本地 Include 依赖", "", "| 来源文件 | 目标文件 |", "| --- | --- |"])
            for edge in cpp.dependencies[:30]:
                lines.append(f"| `{markdown_cell(edge.source)}` | `{markdown_cell(edge.target)}` |")
        else:
            lines.append("当前没有检测到 C++ 源文件或头文件。")

        graph = report.dependencies
        limit = report.options.result_limit
        lines.extend(["", "## 统一依赖图", ""])
        if graph.nodes:
            lines.extend([
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
            ])
            for edge in graph.edges[:limit]:
                lines.append(f"| `{markdown_cell(edge.source)}` | `{markdown_cell(edge.target)}` | {edge.kind} |")
            lines.extend(["", "### 循环依赖", ""])
            if graph.cycles:
                lines.extend(f"- {' -> '.join(f'`{markdown_cell(node)}`' for node in cycle)}" for cycle in graph.cycles[:limit])
            else:
                lines.append("未检测到循环依赖。")
            lines.extend(["", "### 孤立模块", ""])
            if graph.isolated_nodes:
                lines.extend(f"- `{markdown_cell(node)}`" for node in graph.isolated_nodes[:limit])
            else:
                lines.append("未检测到孤立模块。")
        else:
            lines.append("当前配置未生成统一依赖图。")

        insights = report.insights
        lines.extend(["", "## 推荐阅读顺序", ""])
        if insights.reading_order:
            lines.extend(["| 排名 | 文件 | 语言 | 总分 | 入口距离 | 推荐原因 |", "| ---: | --- | --- | ---: | ---: | --- |"])
            for item in insights.reading_order[:limit]:
                distance = item.entry_distance if item.entry_distance is not None else "不可达"
                lines.append(
                    f"| {item.rank} | `{markdown_cell(item.path)}` | {item.language} | {item.score:.2f} | {distance} | {markdown_cell('；'.join(item.reasons))} |"
                )
        else:
            lines.append("当前配置未生成推荐阅读顺序。")

        lines.extend(["", "## 核心模块评分", ""])
        if insights.module_scores:
            lines.extend(["| 文件 | 规模 | 依赖 | 入口 | Git | 总分 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
            for item in sorted(insights.module_scores, key=lambda score: (-score.total_score, score.path))[:limit]:
                lines.append(
                    f"| `{markdown_cell(item.path)}` | {item.size_score:.2f} | {item.dependency_score:.2f} | {item.entry_score:.2f} | {item.git_score:.2f} | {item.total_score:.2f} |"
                )
        else:
            lines.append("暂无核心模块评分。")

        lines.extend(["", "## 风险热点", ""])
        if insights.hotspots:
            lines.extend(["| 文件 | 语言 | 依赖分 | 修改次数 | 风险分 |", "| --- | --- | ---: | ---: | ---: |"])
            for item in insights.hotspots[:limit]:
                lines.append(
                    f"| `{markdown_cell(item.path)}` | {item.language} | {item.dependency_score:.2f} | {item.git_changes} | {item.risk_score:.2f} |"
                )
        else:
            lines.append("未检测到同时具有依赖中心度和修改热度的文件。")

        lines.extend(["", "## Git 历史", ""])
        if not git.available:
            lines.append("未检测到可用的 Git 历史。")
        else:
            lines.extend([
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
            ])
            for author, count in git.authors.most_common(10):
                lines.append(f"| {markdown_cell(author)} | {count} |")
            lines.extend(["", "### 最近提交", "", "| 提交 | 作者 | 日期 | 摘要 |", "| --- | --- | --- | --- |"])
            for commit in git.recent_commits:
                lines.append(
                    f"| `{markdown_cell(commit.identifier)}` | {markdown_cell(commit.author)} | {commit.date} | {markdown_cell(commit.subject)} |"
                )
            lines.extend(["", "### 高频修改路径", "", "| 路径 | 修改次数 |", "| --- | ---: |"])
            for path, count in git.changed_paths.most_common(15):
                lines.append(f"| `{markdown_cell(path)}` | {count} |")
            lines.extend(["", "### 提交趋势", "", "| 月份 | 提交数 |", "| --- | ---: |"])
            for month, count in sorted(git.commits_by_month.items()):
                lines.append(f"| `{markdown_cell(month)}` | {count} |")
            lines.extend(["", "### 月度代码变化", "", "| 月份 | 提交 | 新增 | 删除 |", "| --- | ---: | ---: | ---: |"])
            for month, change in sorted(git.monthly_changes.items()):
                lines.append(f"| `{month}` | {change.commits} | {change.additions} | {change.deletions} |")
            lines.extend(["", "### 文件变更热点", "", "| 文件 | 提交 | 文件新增 | 文件删除 | 文件修改 | 新增行 | 删除行 | Churn |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
            hottest = sorted(git.file_changes.items(), key=lambda item: (-item[1].churn, item[0]))
            for path, change in hottest[:limit]:
                lines.append(
                    f"| `{markdown_cell(path)}` | {change.commits} | {change.added} | {change.deleted} | {change.modified} | {change.additions} | {change.deletions} | {change.churn} |"
                )
            lines.extend(["", "### 共同修改文件", "", "| 文件 A | 文件 B | 次数 |", "| --- | --- | ---: |"])
            for (left, right), count in git.co_changes.most_common(limit):
                lines.append(f"| `{markdown_cell(left)}` | `{markdown_cell(right)}` | {count} |")
            lines.extend(["", "### 目录贡献者", "", "| 目录 | 主要贡献者 | 文件变更 |", "| --- | --- | ---: |"])
            for directory, authors in sorted(git.directory_authors.items()):
                if authors:
                    author, count = authors.most_common(1)[0]
                    lines.append(f"| `{markdown_cell(directory)}` | {markdown_cell(author)} | {count} |")
            lines.extend(["", "### 活跃与稳定文件", ""])
            lines.append(f"- 最近 90 天活跃：{len(git.active_paths)} 个")
            lines.append(f"- 超过 90 天未修改：{len(git.stable_paths)} 个")

        lines.extend(["", "## Analyzer 耗时", "", "| Analyzer | 秒 |", "| --- | ---: |"])
        for name, duration in report.analyzer_durations.items():
            lines.append(f"| `{markdown_cell(name)}` | {duration:.6f} |")

        lines.extend(["", "## 文件清单", "", "| 文件 | 语言 | 非空行 |", "| --- | --- | ---: |"])
        for file in sorted(files, key=lambda item: (item.non_empty_lines, str(item.path)), reverse=True):
            lines.append(f"| `{markdown_cell(repository.relative_path(file.path))}` | {markdown_cell(file.language)} | {file.non_empty_lines} |")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _timestamp() -> str:
        """返回带时区的当前时间字符串。"""
        from datetime import datetime

        return datetime.now().astimezone().isoformat(timespec="seconds")
