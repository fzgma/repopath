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
            },
            "languages": {
                language: {"files": count, "non_empty_lines": report.stats.language_lines[language]}
                for language, count in report.stats.language_counts.items()
            },
            "directories": dict(report.stats.directory_counts),
            "python": {
                "imports": dict(report.python.import_counts),
                "entry_points": [
                    {"path": report.repository.relative_path(entry.path), "reason": entry.reason}
                    for entry in report.python.entry_points
                ],
                "core_modules": [
                    {"name": module.name, "lines": module.lines, "references": module.references}
                    for module in report.python.core_modules
                ],
                "dependencies": [
                    {"source": edge.source, "target": edge.target}
                    for edge in report.python.dependencies
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
