"""JSON 报告 Renderer。"""

import json

from ..model.report import RepositoryReport


class JsonRenderer:
    """将 RepositoryReport 转换为机器可读的 JSON。"""

    def render(self, report: RepositoryReport) -> str:
        """生成包含所有主要分析结果的 JSON 文本。"""
        payload = {
            "repository": {"name": report.repository.name, "root": str(report.repository.root)},
            "overview": {
                "file_count": len(report.files),
                "non_empty_lines": report.stats.total_non_empty_lines,
                "language_count": len(report.stats.language_counts),
                "entry_point_count": len(report.python.entry_points),
                "cpp_entry_point_count": len(report.cpp.entry_points),
                "comment_lines": report.stats.total_comment_lines,
            },
            "languages": {
                language: {"files": count, "non_empty_lines": report.stats.language_family_lines[language]}
                for language, count in report.stats.language_family_counts.items()
            },
            "directories": dict(report.stats.directory_counts),
            "python": {
                "function_count": report.python.function_count,
                "class_count": report.python.class_count,
                "imports": dict(report.python.import_counts),
                "entry_points": [
                    {"path": report.repository.relative_path(entry.path), "reason": entry.reason}
                    for entry in report.python.entry_points
                ],
                "core_modules": [
                    {"name": module.name, "lines": module.lines, "references": module.references, "score": module.score}
                    for module in report.python.core_modules
                ],
                "dependencies": [
                    {"source": edge.source, "target": edge.target, "kind": edge.kind}
                    for edge in report.python.dependencies
                ],
            },
            "cpp": {
                "file_count": len(report.cpp.files),
                "function_count": report.cpp.function_count,
                "type_count": report.cpp.type_count,
                "namespace_count": report.cpp.namespace_count,
                "includes": dict(report.cpp.include_counts),
                "entry_points": [
                    {"path": report.repository.relative_path(entry.path), "line": entry.line}
                    for entry in report.cpp.entry_points
                ],
                "dependencies": [
                    {"source": edge.source, "target": edge.target, "kind": edge.kind}
                    for edge in report.cpp.dependencies
                ],
                "symbols": [
                    {
                        "path": report.repository.relative_path(path),
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "line": symbol.line,
                    }
                    for path, item in report.cpp.files.items()
                    for symbol in [*item.functions, *item.types, *item.namespaces]
                ],
            },
            "git": {
                "available": report.git.available,
                "commit_count": report.git.commit_count,
                "authors": dict(report.git.authors),
                "commits_by_month": dict(report.git.commits_by_month),
                "recent_commits": [
                    {"commit": commit, "author": author, "date": date, "subject": subject}
                    for commit, author, date, subject in report.git.recent_commits
                ],
                "changed_paths": dict(report.git.changed_paths),
                "first_commit_date": report.git.first_commit_date,
                "last_commit_date": report.git.last_commit_date,
                "error": report.git.error,
            },
            "files": [
                {
                    "path": report.repository.relative_path(file.path),
                    "language": str(file.language),
                    "lines": file.lines,
                    "non_empty_lines": file.non_empty_lines,
                }
                for file in report.files
            ],
            "warnings": report.warnings,
            "errors": report.errors,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
