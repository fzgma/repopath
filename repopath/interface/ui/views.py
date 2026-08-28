"""Streamlit 报告视图组件。"""

import json
from collections.abc import Callable, Iterable, Sequence
from heapq import nsmallest
from itertools import islice
from typing import Any, TypeAlias, TypeVar

from ...model.dependency import DependencyEdge
from ...model.git import FileChangeStats
from ...model.report import RepositoryReport
from ...renderer.json import JsonRenderer
from ...renderer.markdown import MarkdownRenderer
from .state import AnalysisSnapshot, UiRunState


StreamlitApi: TypeAlias = Any
Row: TypeAlias = dict[str, object]
Item = TypeVar("Item")


def render_snapshot(
    snapshot: AnalysisSnapshot, st: StreamlitApi
) -> None:
    """展示当前运行状态、错误或已完成的报告。"""
    if snapshot.active:
        st.progress(
            snapshot.progress_percent,
            text=snapshot.current_stage,
        )
    elif snapshot.state is UiRunState.CANCELLED:
        st.warning("分析已停止。")
    elif (
        snapshot.state is UiRunState.ERROR
        and snapshot.error is not None
    ):
        error = snapshot.error
        st.error(f"{error.category}错误：{error.summary}")
        st.info(error.suggestion)
        with st.expander("查看详细错误"):
            st.code(error.details)
    elif snapshot.report is not None:
        render_report(snapshot.report, st, cache_key=snapshot.job_id)
    else:
        st.info("输入本地目录或 GitHub 公开仓库地址后开始分析。")


def render_report(
    report: RepositoryReport,
    st: StreamlitApi,
    *,
    cache_key: str | None = None,
) -> None:
    """只渲染用户当前选择的报告视图。"""
    graph = report.dependencies
    metrics = st.columns(6)
    values: list[tuple[str, object, str | None]] = [
        ("文件数", len(report.files), None),
        ("非空行", report.stats.total_non_empty_lines, None),
        ("语言", len(report.stats.language_family_counts), None),
        (
            "入口",
            len(graph.entry_nodes),
            "可作为程序或脚本起点识别到的模块数量。",
        ),
        (
            "依赖",
            len(graph.edges),
            "统一依赖图中已识别的直接依赖边数量。",
        ),
        ("耗时", f"{report.elapsed_seconds:.2f}s", None),
    ]
    for column, (label, value, help_text) in zip(
        metrics, values, strict=True
    ):
        column.metric(label, value, help=help_text)
    _render_messages(report, st)
    _render_analysis_scope_hint(report, st)
    view = st.segmented_control(
        "报告视图",
        [
            "概览",
            "推荐阅读",
            "依赖关系",
            "Python",
            "C++",
            "Git",
            "报告",
        ],
        default="概览",
        selection_mode="single",
        key="report_view",
    )
    match view:
        case "概览":
            _render_overview(report, st)
        case "推荐阅读":
            _render_reading(report, st)
        case "依赖关系":
            _render_dependencies(report, st)
        case "Python":
            _render_python(report, st)
        case "C++":
            _render_cpp(report, st)
        case "Git":
            _render_git(report, st)
        case "报告":
            _render_downloads(report, st, cache_key=cache_key)
        case _:
            _render_overview(report, st)


def _render_messages(
    report: RepositoryReport, st: StreamlitApi
) -> None:
    """聚合展示分析警告和局部 Analyzer 错误。"""
    if not report.warnings and not report.errors:
        return
    with st.expander(
        f"分析提示（{len(report.warnings) + len(report.errors)}）"
    ):
        if report.errors:
            st.warning("部分 Analyzer 执行失败，报告可能不完整。")
            for message in report.errors:
                st.write(f"- {message}")
        for message in report.warnings:
            st.info(message)


def _render_analysis_scope_hint(
    report: RepositoryReport, st: StreamlitApi
) -> None:
    """说明当前分析模式未启用的结果类型及切换建议。"""
    options = report.options
    hints: list[str] = []
    if not options.dependencies_enabled:
        hints.append(
            "依赖分析未启用，依赖关系、推荐阅读和结构热点不会生成。"
        )
    if not options.git_enabled:
        hints.append("Git 分析未启用，Git 变更热点不会生成。")
    if not hints:
        return
    with st.expander("分析范围提示", expanded=True):
        for hint in hints:
            st.warning(hint)
        if options.profile != "deep":
            st.info("切换到“深度”模式后重新分析，可生成完整导航结果。")


def _render_overview(
    report: RepositoryReport, st: StreamlitApi
) -> None:
    """展示语言、目录、风险热点和分析耗时概览。"""
    stats = report.stats
    if report.github_rate_limit is not None:
        rate_limit = report.github_rate_limit
        st.subheader("GitHub API 额度")
        limit, remaining, reset = st.columns(3)
        limit.metric(
            "限额",
            rate_limit.limit,
            help="当前 Token 或公网 IP 在 Core API 时间窗口中的总请求额度。",
        )
        remaining.metric(
            "剩余",
            rate_limit.remaining,
            help="下载本次快照前读取到的可用 Core API 请求次数。",
        )
        reset.metric(
            "重置时间",
            rate_limit.reset_at.strftime("%Y-%m-%d %H:%M:%S %z"),
            help="GitHub Core API 额度恢复的本地时间。",
        )
    left, right = st.columns(2)
    language_rows: list[Row] = [
        {
            "语言": language,
            "文件数": count,
            "非空行": stats.language_family_lines[language],
        }
        for language, count in (
            stats.language_family_counts.most_common()
        )
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
            st.dataframe(
                language_rows, width="stretch", hide_index=True
            )
        else:
            st.info("没有可展示的语言统计。")
    directory_rows: list[Row] = [
        {
            "目录": directory,
            "文件数": count,
            "非空行": stats.directory_lines[directory],
        }
        for directory, count in stats.directory_counts.most_common(15)
    ]
    with right:
        st.subheader("主要目录")
        if directory_rows:
            st.bar_chart(
                directory_rows,
                x="目录",
                y="非空行",
                horizontal=True,
                color="#D97706",
            )
            st.dataframe(
                directory_rows, width="stretch", hide_index=True
            )
        else:
            st.info("没有可展示的目录统计。")
    st.subheader(
        "结构热点",
        help="风险分等于依赖分加 Git 分；仅展示同时有依赖关系和 Git 修改记录的模块。",
    )
    scores = {
        item.node_id: item for item in report.insights.module_scores
    }
    rows: list[Row] = [
        {
            "路径": item.path,
            "语言": item.language,
            "依赖分": item.dependency_score,
            "Git 修改": item.git_changes,
            "代码行": scores[item.node_id].lines
            if item.node_id in scores
            else 0,
            "风险分": item.risk_score,
        }
        for item in report.insights.hotspots[
            : report.options.result_limit
        ]
    ]
    if rows:
        st.scatter_chart(
            rows,
            x="依赖分",
            y="Git 修改",
            color="语言",
            size="代码行",
            height=360,
        )
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        if (
            not report.options.dependencies_enabled
            or not report.options.git_enabled
        ):
            st.info("结构热点需要同时启用依赖分析和 Git 分析。")
        else:
            st.info("当前没有同时具有依赖中心度和 Git 修改热度的文件。")
    with st.expander("Analyzer 耗时"):
        durations: list[Row] = [
            {"Analyzer": name, "秒": duration}
            for name, duration in report.analyzer_durations.items()
        ]
        if durations:
            st.bar_chart(
                durations,
                x="Analyzer",
                y="秒",
                horizontal=True,
                color="#3A7D44",
            )


def _render_reading(report: RepositoryReport, st: StreamlitApi) -> None:
    """展示筛选后的阅读路线、评分明细和模块详情。"""
    all_items = report.insights.reading_order
    reading_limit = report.options.reading_limit
    filters = st.columns(4)
    with filters[0]:
        language = st.selectbox(
            "阅读语言",
            ["全部", *sorted({item.language for item in all_items})],
            key="reading_language",
        )
    with filters[1]:
        directory = st.selectbox(
            "阅读目录",
            [
                "全部",
                *sorted(
                    {_top_directory(item.path) for item in all_items}
                ),
            ],
            key="reading_directory",
        )
    with filters[2]:
        keyword = st.text_input("路径关键词", key="reading_keyword")
    with filters[3]:
        sort_by = st.selectbox(
            "阅读排序", ["推荐顺序", "核心评分"], key="reading_sort"
        )
    items = [
        item
        for item in all_items
        if (language == "全部" or item.language == language)
        and (
            directory == "全部"
            or _top_directory(item.path) == directory
        )
        and (not keyword or keyword.lower() in item.path.lower())
    ]
    if sort_by == "核心评分":
        visible = _limited_sorted(
            items,
            reading_limit,
            key=lambda item: (-item.score, item.path),
        )
    else:
        visible = items[:reading_limit]
    _caption_count(st, len(items), len(all_items), reading_limit)
    if not items:
        if not report.options.insights_enabled:
            st.info("推荐阅读未启用；切换到“深度”模式后重新分析。")
        else:
            st.info("当前没有符合筛选条件的推荐阅读模块。")
        return
    rows: list[Row] = [
        {
            "排名": item.rank,
            "路径": item.path,
            "语言": item.language,
            "总分": item.score,
            "入口距离": str(item.entry_distance)
            if item.entry_distance is not None
            else "不可达",
            "推荐原因": "；".join(item.reasons),
        }
        for item in visible
    ]
    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        key="reading_order_table",
    )
    selected_path = st.selectbox(
        "查看模块详情",
        [item.path for item in visible],
        key="selected_module",
    )
    _render_module_detail(report, selected_path, st)
    st.subheader(
        "评分明细",
        help=(
            "总分最高 100 分：规模最高 20 分；依赖分最高 35 分，"
            "每个入边计 7 分、每个出边计 2 分；入口分最高 20 分，"
            "每远离入口一层减 4 分；Git 分最高 25 分。"
        ),
    )
    score_items = _limited_sorted(
        report.insights.module_scores,
        reading_limit,
        key=lambda item: (-item.total_score, item.path),
    )
    scores: list[Row] = [
        {
            "路径": item.path,
            "语言": item.language,
            "规模": item.size_score,
            "依赖": item.dependency_score,
            "入口": item.entry_score,
            "Git": item.git_score,
            "总分": item.total_score,
        }
        for item in score_items
    ]
    st.dataframe(scores, width="stretch", hide_index=True)
    if report.insights.reading_paths:
        with st.expander("入口到推荐模块的依赖路径"):
            rows: list[Row] = [
                {
                    "入口": item.entry,
                    "目标": item.target,
                    "路径": " -> ".join(item.nodes),
                }
                for item in report.insights.reading_paths[
                    :reading_limit
                ]
            ]
            st.dataframe(rows, width="stretch", hide_index=True)


def _render_module_detail(
    report: RepositoryReport, path: str, st: StreamlitApi
) -> None:
    """展示选中模块的评分、依赖关系和入口路径。"""
    graph = report.dependencies
    node = next(
        (node for node in graph.nodes.values() if node.path == path),
        None,
    )
    if node is None:
        return
    score = next(
        (
            item
            for item in report.insights.module_scores
            if item.node_id == node.id
        ),
        None,
    )
    recommendation = next(
        (
            item
            for item in report.insights.reading_order
            if item.node_id == node.id
        ),
        None,
    )
    with st.expander("模块详情", expanded=True):
        if score is not None:
            distance = (
                score.entry_distance
                if score.entry_distance is not None
                else "不可达"
            )
            st.write(
                f"核心评分：{score.total_score}；入口距离：{distance}"
            )
        if recommendation is not None:
            st.write(f"推荐原因：{'；'.join(recommendation.reasons)}")
        dependencies = [
            graph.nodes[item].path
            for item in graph.dependencies_of(node.id)
            if item in graph.nodes
        ]
        dependents = [
            graph.nodes[item].path
            for item in graph.dependents_of(node.id)
            if item in graph.nodes
        ]
        columns = st.columns(2)
        columns[0].write(
            "正向依赖："
            + ("、".join(dependencies) if dependencies else "无")
        )
        columns[1].write(
            "反向依赖："
            + ("、".join(dependents) if dependents else "无")
        )


def _top_directory(path: str) -> str:
    """返回报告路径的顶层目录名称。"""
    return path.split("/", 1)[0] if "/" in path else "."


def _render_dependencies(
    report: RepositoryReport, st: StreamlitApi
) -> None:
    """展示统一依赖边、目录聚合、循环和孤立模块。"""
    graph = report.dependencies
    if not graph.nodes:
        if not report.options.dependencies_enabled:
            st.info("依赖分析未启用；切换到“深度”模式后重新分析。")
        else:
            st.info("当前没有可展示的依赖节点。")
        return
    filters = st.columns(4)
    with filters[0]:
        language = st.selectbox(
            "语言筛选",
            [
                "全部",
                *sorted(
                    {node.language for node in graph.nodes.values()}
                ),
            ],
            key="dependency_language",
        )
    with filters[1]:
        directory = st.selectbox(
            "目录筛选",
            [
                "全部",
                *sorted(
                    {
                        _top_directory(node.path)
                        for node in graph.nodes.values()
                    }
                ),
            ],
            key="dependency_directory",
        )
    with filters[2]:
        keyword = st.text_input("路径筛选", key="dependency_keyword")
    with filters[3]:
        sort_by = st.selectbox(
            "依赖排序", ["来源路径", "目标路径"], key="dependency_sort"
        )
    nodes = {
        node_id
        for node_id, node in graph.nodes.items()
        if (language == "全部" or node.language == language)
        and (
            directory == "全部"
            or _top_directory(node.path) == directory
        )
        and (not keyword or keyword.lower() in node.path.lower())
    }

    def edge_matches(edge: DependencyEdge) -> bool:
        """判断依赖边的两端是否都通过当前筛选条件。"""
        return edge.source in nodes and edge.target in nodes

    if sort_by == "目标路径":

        def edge_key(edge: DependencyEdge) -> tuple[str, str]:
            """按依赖目标和来源路径排序。"""
            return (
                graph.nodes[edge.target].path,
                graph.nodes[edge.source].path,
            )
    else:

        def edge_key(edge: DependencyEdge) -> tuple[str, str]:
            """按依赖来源和目标路径排序。"""
            return (
                graph.nodes[edge.source].path,
                graph.nodes[edge.target].path,
            )

    total_edges = sum(edge_matches(edge) for edge in graph.edges)
    graph_edges = (
        [edge for edge in graph.edges if edge_matches(edge)]
        if total_edges <= 50 and len(nodes) <= 30
        else []
    )
    edges = _limited_sorted(
        (edge for edge in graph.edges if edge_matches(edge)),
        report.options.result_limit,
        key=edge_key,
    )
    _caption_count(
        st, total_edges, len(graph.edges), report.options.result_limit
    )
    if len(nodes) <= 30 and graph_edges:
        st.graphviz_chart(
            _dependency_dot(report, nodes, graph_edges), width="stretch"
        )
    rows: list[Row] = [
        {
            "来源": graph.nodes[edge.source].path,
            "目标": graph.nodes[edge.target].path,
            "类型": edge.kind,
        }
        for edge in edges
    ]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("当前筛选条件下没有依赖边。")
    with st.expander("目录依赖聚合", expanded=len(graph.nodes) > 30):
        rows: list[Row] = [
            {"来源目录": source, "目标目录": target, "依赖数": count}
            for (
                source,
                target,
            ), count in graph.directory_edges.most_common(
                report.options.result_limit
            )
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的跨目录依赖。")
    left, right = st.columns(2)
    with left:
        st.subheader(
            "循环依赖",
            help=(
                "每组成员可经仓库内依赖关系互相到达，形成闭环；"
                "成员列表不表示实际依赖顺序。"
            ),
        )
        if graph.cycles:
            for index, cycle in enumerate(
                graph.cycles[: report.options.result_limit], start=1
            ):
                st.warning(
                    f"循环组 {index}（{len(cycle)} 个模块）\n\n"
                    + "\n".join(
                        f"- `{graph.nodes[node].path}`"
                        for node in cycle
                    )
                )
        else:
            st.success("未检测到循环依赖。")
    with right:
        st.subheader("孤立模块")
        rows: list[Row] = [
            {
                "路径": graph.nodes[node_id].path,
                "语言": graph.nodes[node_id].language,
            }
            for node_id in graph.isolated_nodes[
                : report.options.result_limit
            ]
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.success("未检测到孤立模块。")


def _dependency_dot(
    report: RepositoryReport,
    nodes: set[str],
    edges: Sequence[DependencyEdge],
) -> str:
    """将筛选后的依赖关系转换为 Graphviz DOT 文本。"""
    lines = [
        "digraph dependencies {",
        "rankdir=LR;",
        'node [shape=box, style="rounded,filled"];',
    ]
    for node_id in sorted(nodes):
        node = report.dependencies.nodes[node_id]
        color = "#DCEAF7" if node.language == "Python" else "#FDE6C8"
        lines.append(
            f"{json.dumps(node_id)} [label={json.dumps(node.label)}, "
            f"fillcolor={json.dumps(color)}];"
        )
    lines.extend(
        f"{json.dumps(edge.source)} -> {json.dumps(edge.target)};"
        for edge in edges
    )
    return "\n".join([*lines, "}"])


def _render_python(report: RepositoryReport, st: StreamlitApi) -> None:
    """展示 Python import、依赖和符号。"""
    python = report.python
    if not python.module_paths:
        if not report.options.python_enabled:
            st.info(
                "Python 分析未启用；切换到“标准”或“深度”模式后重新分析。"
            )
        else:
            st.info("当前仓库没有可分析的 Python 文件。")
        return
    metrics = st.columns(4)
    metrics[0].metric("模块", len(python.module_paths))
    metrics[1].metric("函数", python.function_count)
    metrics[2].metric("类", python.class_count)
    metrics[3].metric("入口", len(python.entry_points))
    st.subheader("Python import")
    rows: list[Row] = [
        {"模块": name, "引用次数": count}
        for name, count in python.import_counts.most_common(
            report.options.result_limit
        )
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    with st.expander("Python 符号"):
        symbols: list[Row] = list(
            islice(
                (
                    {
                        "文件": report.repository.relative_path(path),
                        "名称": symbol.name,
                        "类型": symbol.kind,
                        "行号": symbol.line,
                    }
                    for path, items in python.symbols_by_file.items()
                    for symbol in items
                ),
                report.options.result_limit,
            )
        )
        st.dataframe(
            symbols,
            width="stretch",
            hide_index=True,
        )


def _render_cpp(report: RepositoryReport, st: StreamlitApi) -> None:
    """展示 C++ include、符号和入口。"""
    cpp = report.cpp
    if not cpp.files:
        if not report.options.cpp_enabled:
            st.info(
                "C++ 分析未启用；切换到“标准”或“深度”模式后重新分析。"
            )
        else:
            st.info("当前仓库没有可分析的 C++ 文件。")
        return
    metrics = st.columns(4)
    metrics[0].metric("文件", len(cpp.files))
    metrics[1].metric("函数", cpp.function_count)
    metrics[2].metric("类/结构体", cpp.type_count)
    metrics[3].metric("命名空间", cpp.namespace_count)
    st.subheader("常用 Include")
    rows: list[Row] = [
        {"Include": name, "引用次数": count}
        for name, count in cpp.include_counts.most_common(
            report.options.result_limit
        )
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    with st.expander("C++ 符号"):
        symbols: list[Row] = list(
            islice(
                (
                    {
                        "文件": report.repository.relative_path(path),
                        "名称": symbol.name,
                        "类型": symbol.kind,
                        "行号": symbol.line,
                    }
                    for path, item in cpp.files.items()
                    for symbol in [
                        *item.functions,
                        *item.types,
                        *item.namespaces,
                    ]
                ),
                report.options.result_limit,
            )
        )
        st.dataframe(
            symbols,
            width="stretch",
            hide_index=True,
        )


def _render_git(report: RepositoryReport, st: StreamlitApi) -> None:
    """展示 Git 趋势、热点、贡献者和最近提交。"""
    git = report.git
    if not git.available:
        if not report.options.git_enabled:
            st.info(
                "Git 分析未启用；切换到“标准”或“深度”模式后重新分析。"
            )
        else:
            st.info(git.error or "当前目录没有可用的 Git 历史。")
        return
    metrics = st.columns(4)
    metrics[0].metric("提交", git.commit_count)
    metrics[1].metric("贡献者", len(git.authors))
    metrics[2].metric("30 天活跃文件", len(git.recent_30_days))
    metrics[3].metric("90 天活跃文件", len(git.recent_90_days))
    monthly_rows: list[Row] = [
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
        st.line_chart(
            monthly_rows, x="月份", y="提交数", color="#2A6F97"
        )
        st.subheader("代码变化")
        st.bar_chart(
            monthly_rows, x="月份", y=["新增", "删除"], stack=False
        )
    st.subheader(
        "文件变更热点", help="Churn 是文件历史中的新增行与删除行总和。"
    )
    filters = st.columns(3)
    paths = list(git.file_changes)
    with filters[0]:
        directory = st.selectbox(
            "热点目录",
            ["全部", *sorted({_top_directory(path) for path in paths})],
            key="git_directory",
        )
    with filters[1]:
        keyword = st.text_input("热点路径筛选", key="git_keyword")
    with filters[2]:
        sort_by = st.selectbox(
            "热点排序", ["Churn", "路径"], key="git_sort"
        )

    def change_matches(item: tuple[str, FileChangeStats]) -> bool:
        """判断 Git 文件变更是否通过当前筛选条件。"""
        path = item[0]
        return (
            directory == "全部" or _top_directory(path) == directory
        ) and (not keyword or keyword.lower() in path.lower())

    hottest_key: Callable[
        [tuple[str, FileChangeStats]], tuple[object, ...]
    ]
    if sort_by == "路径":
        hottest_key = _git_path_key
    else:
        hottest_key = _git_churn_key
    total_hottest = sum(
        change_matches(item) for item in git.file_changes.items()
    )
    hottest = _limited_sorted(
        (
            item
            for item in git.file_changes.items()
            if change_matches(item)
        ),
        report.options.result_limit,
        key=hottest_key,
    )
    _caption_count(
        st,
        total_hottest,
        len(git.file_changes),
        report.options.result_limit,
    )
    rows: list[Row] = [
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
        for path, change in hottest
    ]
    if rows:
        st.bar_chart(
            rows[:15],
            x="路径",
            y="Churn",
            horizontal=True,
            color="#C44536",
        )
        st.dataframe(rows, width="stretch", hide_index=True)
    with st.expander("共同修改文件"):
        rows: list[Row] = [
            {"文件 A": left, "文件 B": right, "次数": count}
            for (left, right), count in git.co_changes.most_common(
                report.options.result_limit
            )
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的共同修改关系。")
    with st.expander("目录贡献者"):
        rows: list[Row] = [
            {
                "目录": directory,
                "主要贡献者": authors.most_common(1)[0][0],
                "文件变更": authors.most_common(1)[0][1],
            }
            for directory, authors in sorted(
                git.directory_authors.items()
            )
            if authors
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的目录贡献者。")
    with st.expander("最近提交"):
        rows: list[Row] = [
            {
                "提交": item.identifier,
                "作者": item.author,
                "日期": item.date,
                "摘要": item.subject,
            }
            for item in git.recent_commits[
                : report.options.result_limit
            ]
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("没有可展示的最近提交。")


def _render_downloads(
    report: RepositoryReport,
    st: StreamlitApi,
    *,
    cache_key: str | None = None,
) -> None:
    """展示报告预览并提供完整 Markdown 和 JSON 下载。"""
    markdown = _cached_report_text(
        report, st, "markdown", MarkdownRenderer().render, cache_key
    )
    json_text = _cached_report_text(
        report, st, "json", JsonRenderer().render, cache_key
    )
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
    show_markdown = st.checkbox(
        "显示 Markdown 预览", value=False, key="show_markdown_preview"
    )
    if show_markdown:
        st.code(markdown, language="markdown")
    show_json = st.checkbox(
        "显示原始 JSON", value=False, key="show_json_preview"
    )
    if show_json:
        st.code(json_text, language="json")


def _cached_report_text(
    report: RepositoryReport,
    st: StreamlitApi,
    format_name: str,
    render: Callable[[RepositoryReport], str],
    cache_key: str | None,
) -> str:
    """按任务编号缓存完整报告文本，避免 fragment 重复序列化。"""
    if cache_key is None:
        return render(report)
    session_state = getattr(st, "session_state", None)
    if session_state is None:
        return render(report)
    key = f"_repopath_report_{cache_key}_{format_name}"
    cached = session_state.get(key)
    if isinstance(cached, str):
        return cached
    value = render(report)
    for old_key in list(session_state):
        if (
            isinstance(old_key, str)
            and old_key.startswith("_repopath_report_")
            and old_key != key
        ):
            session_state.pop(old_key, None)
    session_state[key] = value
    return value


def _caption_count(
    st: StreamlitApi, current: int, total: int, limit: int
) -> None:
    """说明筛选结果数量及页面展示上限。"""
    st.caption(
        f"当前 {current} / 总计 {total}，页面最多展示 {min(current, limit)} 条。"
    )


def _limited_sorted(
    items: Iterable[Item],
    limit: int,
    *,
    key: Callable[[Item], Any],
) -> list[Item]:
    """只排序并返回页面需要的前若干项。"""
    if isinstance(items, Sequence):
        if len(items) <= limit:
            return sorted(items, key=key)
    return nsmallest(limit, items, key=key)


def _git_path_key(
    item: tuple[str, FileChangeStats],
) -> tuple[str, ...]:
    """返回 Git 文件变更的路径排序键。"""
    return (item[0],)


def _git_churn_key(
    item: tuple[str, FileChangeStats],
) -> tuple[int, str]:
    """返回 Git 文件变更的 Churn 排序键。"""
    return (-item[1].churn, item[0])
