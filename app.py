"""RepoPath Streamlit 页面。"""

from pathlib import Path

from repopath.core.service import analyze_repository
from repopath.model.report import RepositoryReport
from repopath.renderer.markdown import MarkdownRenderer


def _render_report(report: RepositoryReport, st) -> None:
    """将分析报告渲染为 Streamlit 页面内容。"""
    stats = report.stats
    python = report.python
    git = report.git
    st.subheader("概览")
    metrics = st.columns(4)
    metrics[0].metric("文件数", len(report.files))
    metrics[1].metric("非空行数", stats.total_non_empty_lines)
    metrics[2].metric("识别语言", len(stats.language_counts))
    metrics[3].metric("提交数", git.commit_count if git.available else "不可用")

    if report.errors:
        for message in report.errors:
            st.error(message)
    if report.warnings:
        for message in report.warnings:
            st.warning(message)

    overview_tab, structure_tab, dependencies_tab, git_tab, report_tab = st.tabs(
        ["概览", "结构", "依赖", "Git", "Markdown 报告"]
    )
    with overview_tab:
        language_rows = [
            {"语言": language, "文件数": count, "非空行": stats.language_lines[language]}
            for language, count in stats.language_counts.most_common()
        ]
        st.dataframe(language_rows, width="stretch", hide_index=True)
    with structure_tab:
        st.write("主要目录")
        st.dataframe(
            [{"目录": directory, "文件数": count} for directory, count in stats.directory_counts.most_common(15)],
            width="stretch",
            hide_index=True,
        )
        st.write("核心模块候选")
        st.dataframe(
            [
                {"模块": module.name, "非空行": module.lines, "被引用": module.references}
                for module in python.core_modules[:15]
            ],
            width="stretch",
            hide_index=True,
        )
    with dependencies_tab:
        st.write("Python import")
        st.dataframe(
            [{"模块": name, "引用次数": count} for name, count in python.import_counts.most_common(20)],
            width="stretch",
            hide_index=True,
        )
        st.write("本地模块依赖")
        st.dataframe(
            [{"来源": edge.source, "目标": edge.target} for edge in python.dependencies],
            width="stretch",
            hide_index=True,
        )
    with git_tab:
        if not git.available:
            st.info("当前目录没有可用的 Git 历史。")
        else:
            st.write("提交趋势")
            monthly_counts = [count for _, count in sorted(git.commits_by_month.items())]
            st.line_chart({"提交数": monthly_counts})
            st.write("最近提交")
            st.dataframe(
                [
                    {"提交": commit, "作者": author, "日期": date, "摘要": subject}
                    for commit, author, date, subject in git.recent_commits
                ],
                width="stretch",
                hide_index=True,
            )
            st.write("高频修改路径")
            st.dataframe(
                [{"路径": path, "修改次数": count} for path, count in git.changed_paths.most_common(15)],
                width="stretch",
                hide_index=True,
            )
    with report_tab:
        st.code(MarkdownRenderer().render(report), language="markdown")


def main() -> None:
    """启动 Streamlit 页面并处理仓库分析交互。"""
    try:
        import streamlit as st
    except ImportError as exc:
        raise SystemExit("缺少 Streamlit，请先执行：python.exe -m pip install -r requirements.txt") from exc

    st.set_page_config(page_title="RepoPath", layout="wide")
    st.title("RepoPath")
    st.caption("快速建立陌生代码仓库的整体认知")
    repository_path = st.text_input("仓库路径", value=".")
    analyze = st.button("分析仓库", type="primary")
    if analyze:
        with st.spinner("正在分析仓库..."):
            try:
                st.session_state["report"] = analyze_repository(Path(repository_path).expanduser())
            except Exception as exc:
                st.error(f"分析失败：{exc}")
    report = st.session_state.get("report")
    if report is not None:
        _render_report(report, st)
    else:
        st.info("输入仓库路径后点击“分析仓库”。")


if __name__ == "__main__":
    main()
