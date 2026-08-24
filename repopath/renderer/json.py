"""JSON 报告 Renderer。"""

import json

from ..model.report import RepositoryReport


class JsonRenderer:
    """将 RepositoryReport 转换为机器可读的 JSON。"""

    def render(self, report: RepositoryReport) -> str:
        """生成包含所有主要分析结果的 JSON 文本。"""
        payload: dict[str, object] = {
            "schema_version": report.schema_version,
            "tool_version": report.tool_version,
            "generated_at": report.generated_at,
            "repository": {
                "name": report.repository.name,
                "root": str(report.repository.root),
                "source_type": str(report.source.type) if report.source else "local",
                "source_location": report.source.location if report.source else str(report.repository.root),
            },
            "overview": {
                "file_count": len(report.files),
                "non_empty_lines": report.stats.total_non_empty_lines,
                "language_count": len(report.stats.language_counts),
                "entry_point_count": len(report.python.entry_points),
                "cpp_entry_point_count": len(report.cpp.entry_points),
                "comment_lines": report.stats.total_comment_lines,
                "dependency_nodes": len(report.dependencies.nodes),
                "dependency_edges": len(report.dependencies.edges),
                "cycle_count": len(report.dependencies.cycles),
                "elapsed_seconds": report.elapsed_seconds,
            },
            "analysis": {
                "profile": report.options.profile,
                "git_period": report.options.git_period,
                "result_limit": report.options.result_limit,
                "analyzer_durations": report.analyzer_durations,
            },
            "languages": {
                language: {"files": count, "non_empty_lines": report.stats.language_family_lines[language]}
                for language, count in report.stats.language_family_counts.items()
            },
            "directories": dict(report.stats.directory_counts),
            "directory_stats": {
                directory: {
                    "files": count,
                    "non_empty_lines": report.stats.directory_lines[directory],
                }
                for directory, count in report.stats.directory_counts.items()
            },
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
            "dependencies": {
                "nodes": [
                    {
                        "id": node.id,
                        "label": node.label,
                        "path": node.path,
                        "language": node.language,
                        "kind": node.kind,
                        "incoming": report.dependencies.incoming_counts[node.id],
                        "outgoing": report.dependencies.outgoing_counts[node.id],
                    }
                    for node in report.dependencies.nodes.values()
                ],
                "directory_nodes": [
                    {
                        "id": node.id,
                        "label": node.label,
                        "path": node.path,
                        "kind": node.kind,
                    }
                    for node in report.dependencies.directory_nodes.values()
                ],
                "edges": [
                    {"source": edge.source, "target": edge.target, "kind": edge.kind}
                    for edge in report.dependencies.edges
                ],
                "cycles": report.dependencies.cycles,
                "isolated_nodes": report.dependencies.isolated_nodes,
                "entry_nodes": report.dependencies.entry_nodes,
                "directory_edges": [
                    {"source": source, "target": target, "count": count}
                    for (source, target), count in report.dependencies.directory_edges.items()
                ],
            },
            "insights": {
                "module_scores": [
                    {
                        "node_id": item.node_id,
                        "label": item.label,
                        "path": item.path,
                        "language": item.language,
                        "lines": item.lines,
                        "incoming": item.incoming,
                        "outgoing": item.outgoing,
                        "entry_distance": item.entry_distance,
                        "git_changes": item.git_changes,
                        "recent_changes": item.recent_changes,
                        "scores": {
                            "size": item.size_score,
                            "dependency": item.dependency_score,
                            "entry": item.entry_score,
                            "git": item.git_score,
                            "total": item.total_score,
                        },
                    }
                    for item in report.insights.module_scores
                ],
                "reading_order": [
                    {
                        "rank": item.rank,
                        "node_id": item.node_id,
                        "path": item.path,
                        "language": item.language,
                        "score": item.score,
                        "entry_distance": item.entry_distance,
                        "reasons": list(item.reasons),
                    }
                    for item in report.insights.reading_order
                ],
                "reading_paths": [
                    {"entry": item.entry, "target": item.target, "nodes": list(item.nodes)}
                    for item in report.insights.reading_paths
                ],
                "hotspots": [
                    {
                        "node_id": item.node_id,
                        "path": item.path,
                        "language": item.language,
                        "dependency_score": item.dependency_score,
                        "git_changes": item.git_changes,
                        "risk_score": item.risk_score,
                    }
                    for item in report.insights.hotspots
                ],
            },
            "git": {
                "available": report.git.available,
                "commit_count": report.git.commit_count,
                "authors": dict(report.git.authors),
                "commits_by_month": dict(report.git.commits_by_month),
                "recent_commits": [
                    {
                        "commit": commit.identifier,
                        "author": commit.author,
                        "date": commit.date,
                        "subject": commit.subject,
                    }
                    for commit in report.git.recent_commits
                ],
                "changed_paths": dict(report.git.changed_paths),
                "first_commit_date": report.git.first_commit_date,
                "last_commit_date": report.git.last_commit_date,
                "history_period": report.git.history_period,
                "shallow": report.git.shallow,
                "file_changes": {
                    path: {
                        "commits": stats.commits,
                        "additions": stats.additions,
                        "deletions": stats.deletions,
                        "added": stats.added,
                        "deleted": stats.deleted,
                        "modified": stats.modified,
                        "churn": stats.churn,
                        "first_changed": stats.first_changed,
                        "last_changed": stats.last_changed,
                    }
                    for path, stats in report.git.file_changes.items()
                },
                "monthly_changes": {
                    month: {
                        "commits": stats.commits,
                        "additions": stats.additions,
                        "deletions": stats.deletions,
                    }
                    for month, stats in report.git.monthly_changes.items()
                },
                "recent_30_days": dict(report.git.recent_30_days),
                "recent_90_days": dict(report.git.recent_90_days),
                "co_changes": [
                    {"left": left, "right": right, "count": count}
                    for (left, right), count in report.git.co_changes.items()
                ],
                "directory_authors": {
                    directory: dict(authors)
                    for directory, authors in report.git.directory_authors.items()
                },
                "active_paths": report.git.active_paths,
                "stable_paths": report.git.stable_paths,
                "error": report.git.error,
            },
            "files": [
                {
                    "path": report.repository.relative_path(file.path),
                    "language": str(file.language),
                    "lines": file.lines,
                    "non_empty_lines": file.non_empty_lines,
                    "comment_lines": file.comment_lines,
                }
                for file in report.files
            ],
            "warnings": report.warnings,
            "errors": report.errors,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
