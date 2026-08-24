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
            f"> 生成时间：{self._timestamp()}",
            "",
            "## 概览",
            "",
            f"- 文件数：{len(files)}",
            f"- 非空行数：{stats.total_non_empty_lines}",
            f"- 识别语言：{len(stats.language_counts)}",
            f"- Python 入口候选：{len(python.entry_points)}",
            f"- C++ 入口候选：{len(cpp.entry_points)}",
            f"- 注释行：{stats.total_comment_lines}",
        ]
        if report.warnings or report.errors:
            lines.extend(["", "## 分析提示", ""])
            lines.extend(f"- 警告：{markdown_cell(message)}" for message in report.warnings)
            lines.extend(f"- 错误：{markdown_cell(message)}" for message in report.errors)

        lines.extend(["", "## 语言统计", "", "| 语言族 | 文件数 | 非空行 | 文件占比 |", "| --- | ---: | ---: | ---: |"])
        for language, count in stats.language_family_counts.most_common():
            percentage = count / len(files) * 100 if files else 0
            lines.append(f"| {markdown_cell(language)} | {count} | {stats.language_family_lines[language]} | {percentage:.1f}% |")

        lines.extend(["", "## 主要目录", "", "| 目录 | 文件数 |", "| --- | ---: |"])
        for directory, count in stats.directory_counts.most_common(15):
            lines.append(f"| `{markdown_cell(directory)}` | {count} |")

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

        lines.extend(["", "## Git 历史", ""])
        if not git.available:
            lines.append("未检测到可用的 Git 历史。")
        else:
            lines.extend([
                f"- 提交数：{git.commit_count}",
                f"- 贡献者数：{len(git.authors)}",
                f"- 首次提交：{git.first_commit_date or '未知'}",
                f"- 最近提交：{git.last_commit_date or '未知'}",
                "",
                "### 主要贡献者",
                "",
                "| 作者 | 提交数 |",
                "| --- | ---: |",
            ])
            for author, count in git.authors.most_common(10):
                lines.append(f"| {markdown_cell(author)} | {count} |")
            lines.extend(["", "### 最近提交", "", "| 提交 | 作者 | 日期 | 摘要 |", "| --- | --- | --- | --- |"])
            for commit, author, date, subject in git.recent_commits:
                lines.append(f"| `{markdown_cell(commit)}` | {markdown_cell(author)} | {date} | {markdown_cell(subject)} |")
            lines.extend(["", "### 高频修改路径", "", "| 路径 | 修改次数 |", "| --- | ---: |"])
            for path, count in git.changed_paths.most_common(15):
                lines.append(f"| `{markdown_cell(path)}` | {count} |")
            lines.extend(["", "### 提交趋势", "", "| 月份 | 提交数 |", "| --- | ---: |"])
            for month, count in sorted(git.commits_by_month.items()):
                lines.append(f"| `{markdown_cell(month)}` | {count} |")

        lines.extend(["", "## 文件清单", "", "| 文件 | 语言 | 非空行 |", "| --- | --- | ---: |"])
        for file in sorted(files, key=lambda item: (item.non_empty_lines, str(item.path)), reverse=True):
            lines.append(f"| `{markdown_cell(repository.relative_path(file.path))}` | {markdown_cell(file.language)} | {file.non_empty_lines} |")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _timestamp() -> str:
        """返回带时区的当前时间字符串。"""
        from datetime import datetime

        return datetime.now().astimezone().isoformat(timespec="seconds")
