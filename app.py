"""RepoPath Streamlit 页面。"""

import json
from pathlib import Path

from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.result import AnalysisProgress
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


PROFILE_NAMES = {
    "快速": "fast",
    "标准": "standard",
    "深度": "deep",
}


def _render_report(report: RepositoryReport, st) -> None:
    """将分析报告渲染为 Streamlit 页面内容。"""
    stats = report.stats
    graph = report.dependencies
    insights = report.insights
    git = report.git
    metrics = st.columns(6)
    metrics[0].metric("文件数", len(report.files))
    metrics[1].metric("非空行", stats.total_non_empty_lines)
    metrics[2].metric("语言", len(stats.language_family_counts))
    metrics[3].metric("入口", len(graph.entry_nodes))
    metrics[4].metric("依赖", len(graph.edges))
    metrics[5].metric("耗时", f"{report.elapsed_seconds:.2f}s")

    _render_messages(report, st)
    tabs = st.tabs(["概览", "推荐阅读", "依赖关系", "Python", "C++", "Git", "报告"])
    with tabs[0]:
        _render_overview(report, st)
    with tabs[1]:
        _render_reading(report, st)
    with tabs[2]:
        _render_dependencies(report, st)
    with tabs[3]:
        _render_python(report, st)
    with tabs[4]:
        _render_cpp(report, st)
    with tabs[5]:
        _render_git(report, st)
    with tabs[6]:
        _render_downloads(report, st)


def _render_messages(report: RepositoryReport, st) -> None:
    """聚合展示分析警告和错误。"""
    if not report.warnings and not report.errors:
        return
    with st.expander(f"分析提示（{len(report.warnings) + len(report.errors)}）"):
        if report.errors:
            st.warning("部分 Analyzer 执行失败，报告可能不完整。")
            for message in report.errors:
                st.write(f"- {message}")
        if report.warnings:
            for message in report.warnings:
                st.info(message)


def _render_overview(report: RepositoryReport, st) -> None:
    """展示语言、目录、热点和 Analyzer 耗时概览。"""
    stats = report.stats
    left, right = st.columns(2)
    language_rows = [
        {
            "语言": language,
            "文件数": count,
            "非空行": stats.language_family_lines[language],
        }
        for language, count in stats.language_family_counts.most_common()
    ]
    with left:
        st.subheader("语言规模")
        if language_rows:
            st.bar_chart(
                language_rows,
                x="语言",
                y="非空行",
                horizontal=True,
                color="#2A6F97",
            )
            st.dataframe(language_rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的语言统计。")
    with right:
        st.subheader("主要目录")
        directory_rows = [
            {
                "目录": directory,
                "文件数": count,
                "非空行": stats.directory_lines[directory],
            }
            for directory, count in stats.directory_counts.most_common(15)
        ]
        if directory_rows:
            st.bar_chart(
                directory_rows,
                x="目录",
                y="非空行",
                horizontal=True,
                color="#D97706",
            )
        else:
            st.info("没有可展示的目录统计。")

    st.subheader("结构热点")
    score_by_id = {item.node_id: item for item in report.insights.module_scores}
    hotspot_rows = [
        {
            "路径": item.path,
            "语言": item.language,
            "依赖分": item.dependency_score,
            "Git 修改": item.git_changes,
            "代码行": score_by_id[item.node_id].lines if item.node_id in score_by_id else 0,
            "风险分": item.risk_score,
        }
        for item in report.insights.hotspots[: report.options.result_limit]
    ]
    if hotspot_rows:
        st.scatter_chart(
            hotspot_rows,
            x="依赖分",
            y="Git 修改",
            color="语言",
            size="代码行",
            height=360,
        )
        st.dataframe(hotspot_rows, width="stretch", hide_index=True)
    else:
        st.info("当前没有同时具有依赖中心度和 Git 修改热度的文件。")

    with st.expander("Analyzer 耗时"):
        duration_rows = [
            {"Analyzer": name, "秒": duration}
            for name, duration in report.analyzer_durations.items()
        ]
        if duration_rows:
            st.bar_chart(duration_rows, x="Analyzer", y="秒", horizontal=True, color="#3A7D44")


def _render_reading(report: RepositoryReport, st) -> None:
    """展示推荐阅读顺序和可解释评分明细。"""
    limit = report.options.result_limit
    all_recommendations = report.insights.reading_order
    filter_columns = st.columns(2)
    with filter_columns[0]:
        language = st.selectbox(
            "阅读语言",
            ["全部", *sorted({item.language for item in all_recommendations})],
            key="reading_language",
        )
    with filter_columns[1]:
        directory = st.selectbox(
            "阅读目录",
            ["全部", *sorted({_top_directory(item.path) for item in all_recommendations})],
            key="reading_directory",
        )
    recommendations = [
        item
        for item in all_recommendations
        if (language == "全部" or item.language == language)
        and (directory == "全部" or _top_directory(item.path) == directory)
    ][:limit]
    if not recommendations:
        st.info("当前配置未生成推荐阅读顺序。")
        return
    rows = [
        {
            "排名": item.rank,
            "路径": item.path,
            "语言": item.language,
            "总分": item.score,
            "入口距离": str(item.entry_distance) if item.entry_distance is not None else "不可达",
            "推荐原因": "；".join(item.reasons),
        }
        for item in recommendations
    ]
    st.dataframe(rows, width="stretch", hide_index=True, key="reading_order_table")

    st.subheader("评分明细")
    score_rows = [
        {
            "路径": item.path,
            "语言": item.language,
            "规模": item.size_score,
            "依赖": item.dependency_score,
            "入口": item.entry_score,
            "Git": item.git_score,
            "总分": item.total_score,
        }
        for item in sorted(
            report.insights.module_scores,
            key=lambda score: (-score.total_score, score.path),
        )[:limit]
    ]
    st.dataframe(score_rows, width="stretch", hide_index=True)

    if report.insights.reading_paths:
        with st.expander("入口到推荐模块的依赖路径"):
            path_rows = [
                {
                    "入口": item.entry,
                    "目标": item.target,
                    "路径": " -> ".join(item.nodes),
                }
                for item in report.insights.reading_paths[:limit]
            ]
            st.dataframe(path_rows, width="stretch", hide_index=True)


def _top_directory(path: str) -> str:
    """返回报告路径的顶层目录名称。"""
    return path.split("/", 1)[0] if "/" in path else "."


def _render_dependencies(report: RepositoryReport, st) -> None:
    """展示可筛选的统一依赖边、循环和孤立模块。"""
    graph = report.dependencies
    if not graph.nodes:
        st.info("当前配置未生成统一依赖图。")
        return
    language = st.selectbox(
        "语言筛选",
        ["全部", *sorted({node.language for node in graph.nodes.values()})],
        key="dependency_language",
    )
    keyword = st.text_input("路径筛选", key="dependency_keyword")
    visible_nodes = {
        node_id
        for node_id, node in graph.nodes.items()
        if (language == "全部" or node.language == language)
        and (not keyword or keyword.lower() in node.path.lower())
    }
    edges = [
        edge
        for edge in graph.edges
        if edge.source in visible_nodes and edge.target in visible_nodes
    ]
    if len(visible_nodes) <= 30 and len(edges) <= 50 and edges:
        st.graphviz_chart(_dependency_dot(report, visible_nodes, edges), width="stretch")
    edge_rows = [
        {
            "来源": graph.nodes[edge.source].path,
            "目标": graph.nodes[edge.target].path,
            "类型": edge.kind,
        }
        for edge in edges[: report.options.result_limit]
    ]
    if edge_rows:
        st.dataframe(edge_rows, width="stretch", hide_index=True)
        if len(edges) > len(edge_rows):
            st.caption(f"显示 {len(edge_rows)} / {len(edges)} 条依赖")
    else:
        st.info("当前筛选条件下没有依赖边。")

    left, right = st.columns(2)
    with left:
        st.subheader("循环依赖")
        if graph.cycles:
            for cycle in graph.cycles[: report.options.result_limit]:
                st.warning(" -> ".join(graph.nodes[node].path for node in cycle))
        else:
            st.success("未检测到循环依赖。")
    with right:
        st.subheader("孤立模块")
        isolated_rows = [
            {"路径": graph.nodes[node_id].path, "语言": graph.nodes[node_id].language}
            for node_id in graph.isolated_nodes[: report.options.result_limit]
        ]
        if isolated_rows:
            st.dataframe(isolated_rows, width="stretch", hide_index=True)
        else:
            st.success("未检测到孤立模块。")


def _dependency_dot(report: RepositoryReport, nodes: set[str], edges) -> str:
    """将筛选后的依赖关系转换为 Graphviz DOT 文本。"""
    graph = report.dependencies
    lines = ["digraph dependencies {", "rankdir=LR;", 'node [shape=box, style="rounded,filled"];']
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        color = "#DCEAF7" if node.language == "Python" else "#FDE6C8"
        lines.append(
            f"{json.dumps(node_id)} [label={json.dumps(node.label)}, fillcolor={json.dumps(color)}];"
        )
    for edge in edges:
        lines.append(f"{json.dumps(edge.source)} -> {json.dumps(edge.target)};")
    lines.append("}")
    return "\n".join(lines)


def _render_python(report: RepositoryReport, st) -> None:
    """展示 Python import、依赖和符号。"""
    python = report.python
    limit = report.options.result_limit
    if not python.module_paths:
        st.info("当前仓库没有可分析的 Python 文件，或该 Analyzer 已关闭。")
        return
    metrics = st.columns(4)
    metrics[0].metric("模块", len(python.module_paths))
    metrics[1].metric("函数", python.function_count)
    metrics[2].metric("类", python.class_count)
    metrics[3].metric("入口", len(python.entry_points))
    st.subheader("Python import")
    st.dataframe(
        [{"模块": name, "引用次数": count} for name, count in python.import_counts.most_common(limit)],
        width="stretch",
        hide_index=True,
    )
    with st.expander("Python 符号"):
        symbols = [
            {
                "文件": report.repository.relative_path(path),
                "名称": symbol.name,
                "类型": symbol.kind,
                "行号": symbol.line,
            }
            for path, items in python.symbols_by_file.items()
            for symbol in items
        ]
        st.dataframe(symbols[:limit], width="stretch", hide_index=True)


def _render_cpp(report: RepositoryReport, st) -> None:
    """展示 C++ include、符号和入口。"""
    cpp = report.cpp
    limit = report.options.result_limit
    if not cpp.files:
        st.info("当前仓库没有可分析的 C++ 文件，或该 Analyzer 已关闭。")
        return
    metrics = st.columns(4)
    metrics[0].metric("文件", len(cpp.files))
    metrics[1].metric("函数", cpp.function_count)
    metrics[2].metric("类/结构体", cpp.type_count)
    metrics[3].metric("命名空间", cpp.namespace_count)
    st.subheader("常用 Include")
    st.dataframe(
        [{"Include": name, "引用次数": count} for name, count in cpp.include_counts.most_common(limit)],
        width="stretch",
        hide_index=True,
    )
    with st.expander("C++ 符号"):
        symbols = [
            {
                "文件": report.repository.relative_path(path),
                "名称": symbol.name,
                "类型": symbol.kind,
                "行号": symbol.line,
            }
            for path, item in cpp.files.items()
            for symbol in [*item.functions, *item.types, *item.namespaces]
        ]
        st.dataframe(symbols[:limit], width="stretch", hide_index=True)


def _render_git(report: RepositoryReport, st) -> None:
    """展示 Git 趋势、文件热点、共同修改和贡献者。"""
    git = report.git
    limit = report.options.result_limit
    if not git.available:
        st.info("当前目录没有可用的 Git 历史，或 Git Analyzer 已关闭。")
        return
    metrics = st.columns(4)
    metrics[0].metric("提交", git.commit_count)
    metrics[1].metric("贡献者", len(git.authors))
    metrics[2].metric("30 天活跃文件", len(git.recent_30_days))
    metrics[3].metric("90 天活跃文件", len(git.recent_90_days))
    monthly_rows = [
        {
            "月份": month,
            "提交数": change.commits,
            "新增": change.additions,
            "删除": change.deletions,
        }
        for month, change in sorted(git.monthly_changes.items())
    ]
    if monthly_rows:
        st.subheader("提交趋势")
        st.line_chart(monthly_rows, x="月份", y="提交数", color="#2A6F97")
        st.subheader("代码变化")
        st.bar_chart(monthly_rows, x="月份", y=["新增", "删除"], stack=False)

    st.subheader("文件变更热点")
    hottest = sorted(git.file_changes.items(), key=lambda item: (-item[1].churn, item[0]))
    hotspot_rows = [
        {
            "路径": path,
            "提交": change.commits,
            "新增": change.additions,
            "删除": change.deletions,
            "文件新增": change.added,
            "文件删除": change.deleted,
            "文件修改": change.modified,
            "Churn": change.churn,
        }
        for path, change in hottest[:limit]
    ]
    if hotspot_rows:
        st.bar_chart(hotspot_rows[:15], x="路径", y="Churn", horizontal=True, color="#C44536")
        st.dataframe(hotspot_rows, width="stretch", hide_index=True)

    with st.expander("共同修改文件"):
        co_change_rows = [
            {"文件 A": left, "文件 B": right, "次数": count}
            for (left, right), count in git.co_changes.most_common(limit)
        ]
        if co_change_rows:
            st.dataframe(co_change_rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的共同修改关系。")
    with st.expander("目录贡献者"):
        contributor_rows = [
            {
                "目录": directory,
                "主要贡献者": authors.most_common(1)[0][0],
                "文件变更": authors.most_common(1)[0][1],
            }
            for directory, authors in sorted(git.directory_authors.items())
            if authors
        ]
        if contributor_rows:
            st.dataframe(contributor_rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的目录贡献者。")


def _render_downloads(report: RepositoryReport, st) -> None:
    """展示报告预览并提供 Markdown 和 JSON 下载。"""
    markdown = MarkdownRenderer().render(report)
    json_text = JsonRenderer().render(report)
    left, right = st.columns(2)
    with left:
        st.download_button(
            "下载 Markdown",
            markdown,
            file_name=f"{report.repository.name}-repopath.md",
            mime="text/markdown",
            width="stretch",
        )
    with right:
        st.download_button(
            "下载 JSON",
            json_text,
            file_name=f"{report.repository.name}-repopath.json",
            mime="application/json",
            width="stretch",
        )
    st.code(markdown, language="markdown")
    with st.expander("原始 JSON"):
        st.json(json_text)


def main() -> None:
    """启动 Streamlit 页面并处理仓库分析交互。"""
    try:
        import streamlit as st
    except ImportError as exc:
        raise SystemExit("缺少 Streamlit，请先执行：python.exe -m pip install -r requirements.txt") from exc

    st.set_page_config(page_title="RepoPath", layout="wide")
    st.title("RepoPath")
    with st.form("analysis_form", clear_on_submit=False):
        repository_path = st.text_input("仓库来源（本地目录）", value=".")
        profile_name = st.segmented_control(
            "分析模式",
            list(PROFILE_NAMES),
            default="深度",
            selection_mode="single",
        )
        analyze = st.form_submit_button("分析仓库", type="primary", width="stretch")
    if analyze:
        st.session_state.pop("report", None)
        progress = st.progress(0, text="正在准备分析")

        def on_progress(event: AnalysisProgress) -> None:
            """将 Pipeline 阶段进度同步到当前页面。"""
            progress.progress(event.percent, text=f"{event.analyzer}：{event.status}")

        try:
            options = AnalysisOptions.for_profile(PROFILE_NAMES[profile_name or "深度"])
            st.session_state["report"] = analyze_repository(
                Path(repository_path).expanduser(),
                options=options,
                progress_callback=on_progress,
            )
            progress.empty()
        except Exception as exc:
            progress.empty()
            st.error(f"分析失败：{exc}")
    report = st.session_state.get("report")
    if report is not None:
        _render_report(report, st)
    else:
        st.info("输入本地仓库路径后开始分析。")


if __name__ == "__main__":
    main()
