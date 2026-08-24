"""Streamlit 页面流程和分析表单。"""

from collections.abc import Callable
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Any, TypeAlias

from ...model.options import AnalysisOptions
from ...model.report import RepositoryReport
from ...model.result import AnalysisProgress
from .profiles import PROFILE_SPECS, label_for_profile, profile_for_label
from .state import begin_run, fail_run, finish_run, get_snapshot, update_progress
from .views import render_snapshot


StreamlitApi: TypeAlias = Any
AnalyzeRepository: TypeAlias = Callable[
    [Path, set[Path] | None, AnalysisOptions | None, Callable[[AnalysisProgress], None] | None],
    RepositoryReport,
]
LoadOptions: TypeAlias = Callable[[Path], AnalysisOptions]
_GIT_PERIODS = {"全部历史": "all", "最近 30 天": "30", "最近 90 天": "90"}


def render_application(st: StreamlitApi, analyze: AnalyzeRepository, load_options: LoadOptions) -> None:
    """渲染分析表单、执行同步任务并展示会话结果。"""
    snapshot = get_snapshot(st.session_state)
    st.title("RepoPath")
    with st.form("analysis_form", clear_on_submit=False):
        source = st.text_input("仓库来源（本地目录）", value=snapshot.source or ".", help="当前版本仅支持本地目录；远程来源将在 Core Provider 支持后开放。")
        configured_options = _default_options(source, load_options)
        default_label = label_for_profile(configured_options.profile)
        label = st.segmented_control(
            "分析模式",
            [spec.label for spec in PROFILE_SPECS],
            default=default_label,
            selection_mode="single",
            help="；".join(f"{spec.label}：{spec.description}" for spec in PROFILE_SPECS),
        )
        with st.expander("高级配置"):
            git_labels = list(_GIT_PERIODS)
            git_label = st.selectbox("Git 时间范围", git_labels, index=git_labels.index(_git_label(configured_options.git_period)), help="限制 Git 历史读取范围；范围越小，Git 分析通常越快。")
            max_file_size_mb = st.number_input("最大文件大小（MB）", min_value=0, value=_megabytes(configured_options.max_file_size), step=1, help="单个可读取文本文件的大小上限；0 表示不限制。")
            result_limit = st.number_input("页面结果数量", min_value=1, value=configured_options.result_limit, step=1, help="限制页面表格和图表展示数量，不影响完整报告下载。")
        submitted = st.form_submit_button("分析仓库", type="primary", width="stretch", disabled=snapshot.state.value == "running")
    if submitted:
        _run_analysis(st, source, label or default_label, git_label, int(max_file_size_mb), int(result_limit), analyze, load_options)
    render_snapshot(get_snapshot(st.session_state), st)


def _default_options(source: str, load_options: LoadOptions) -> AnalysisOptions:
    """读取本地配置作为页面控件的初始选项。"""
    try:
        root = Path(source).expanduser().resolve()
        if root.is_dir():
            return load_options(root)
    except (OSError, ValueError):
        pass
    return AnalysisOptions()


def _git_label(period: str) -> str:
    """将核心 Git 时间范围转换为页面选项标签。"""
    return next(label for label, value in _GIT_PERIODS.items() if value == period)


def _megabytes(size: int | None) -> int:
    """将字节上限转换为页面使用的整数 MB。"""
    return 0 if size is None else ceil(size / (1024 * 1024))


def _run_analysis(st: StreamlitApi, source: str, label: str, git_label: str, max_file_size_mb: int, result_limit: int, analyze: AnalyzeRepository, load_options: LoadOptions) -> None:
    """解析 UI 配置、更新快照并执行一次同步分析。"""
    progress: Any = None
    try:
        root = Path(source).expanduser().resolve()
        base = load_options(root)
        preset = profile_for_label(label).options()
        options = base.with_overrides(
            profile=preset.profile,
            python_enabled=preset.python_enabled,
            cpp_enabled=preset.cpp_enabled,
            git_enabled=preset.git_enabled,
            dependencies_enabled=preset.dependencies_enabled,
            insights_enabled=preset.insights_enabled,
            git_period=_GIT_PERIODS[git_label],
            max_file_size=None if max_file_size_mb == 0 else max_file_size_mb * 1024 * 1024,
            result_limit=result_limit,
        )
        begin_run(st.session_state, source, options)
        progress = st.progress(0, text="正在准备分析")
        started_at = perf_counter()

        def on_progress(event: AnalysisProgress) -> None:
            """将 Pipeline 阶段事件写入会话状态和进度条。"""
            current = update_progress(st.session_state, event)
            progress.progress(current.progress_percent, text=current.current_stage)

        report = analyze(root, None, options, on_progress)
        report.elapsed_seconds = round(perf_counter() - started_at, 6)
        finish_run(st.session_state, report)
        progress.empty()
    except Exception as exc:
        if progress is not None:
            progress.empty()
        fail_run(st.session_state, exc)
