"""Streamlit 页面流程和分析表单。"""

from collections.abc import Callable
from math import ceil
from pathlib import Path
from typing import Any, TypeAlias

from ...model.options import AnalysisOptions
from ...model.repository import (
    GitHubRateLimit,
    RepositorySource,
    RepositorySourceType,
)
from .profiles import (
    PROFILE_SPECS,
    label_for_profile,
    profile_for_label,
)
from .runtime import (
    AnalysisRuntime,
    AnalyzeRepository,
    get_analysis_runtime,
)
from .state import (
    UiRunState,
    clear_github_rate_limit,
    get_github_rate_limit,
    save_github_rate_limit,
)
from .views import render_snapshot


StreamlitApi: TypeAlias = Any
LoadOptions: TypeAlias = Callable[[Path], AnalysisOptions]
EnsureConfig: TypeAlias = Callable[[Path], Path]
FetchGitHubRateLimit: TypeAlias = Callable[[], GitHubRateLimit]
_GIT_PERIODS = {
    "全部历史": "all",
    "最近 30 天": "30",
    "最近 90 天": "90",
}
_SOURCE_TYPES = ("本地目录", "GitHub 公开仓库")


def render_application(
    st: StreamlitApi,
    analyze: AnalyzeRepository,
    load_options: LoadOptions,
    ensure_config: EnsureConfig,
    fetch_rate_limit: FetchGitHubRateLimit,
) -> None:
    """渲染分析表单并轮询当前会话的后台任务快照。"""
    runtime = get_analysis_runtime(st.session_state, analyze)
    snapshot = runtime.snapshot()
    st.title("RepoPath")
    previous_source = (
        snapshot.report.source if snapshot.report is not None else None
    )
    default_source_type = (
        "GitHub 公开仓库"
        if previous_source is not None
        and previous_source.type is RepositorySourceType.GITHUB
        else "本地目录"
    )
    source_type = st.segmented_control(
        "仓库来源",
        _SOURCE_TYPES,
        default=default_source_type,
        selection_mode="single",
        help="本地目录使用仓库内配置；GitHub 公开仓库分析固定到一个提交快照，不读取私有仓库或 Git 演进历史。",
    )
    is_github = source_type == "GitHub 公开仓库"
    source_value = _source_value_for_type(
        snapshot.source,
        previous_source.type if previous_source is not None else None,
        is_github,
    )
    with st.form("analysis_form", clear_on_submit=False):
        source = st.text_input(
            "GitHub 仓库地址" if is_github else "本地仓库目录",
            value=source_value,
            placeholder=(
                "owner/repository 或 "
                "https://github.com/owner/repository"
            )
            if is_github
            else None,
            help=(
                "例如 fzgma/repopath 或 "
                "https://github.com/fzgma/repopath"
            )
            if is_github
            else "输入待分析的本地目录路径。",
            key=f"source:{source_type}",
        )
        reference = (
            st.text_input(
                "分支、标签或提交 SHA（可选）",
                help="留空时读取 GitHub 仓库默认分支；分析会固定到解析出的提交 SHA。",
                key="github-reference",
            )
            if is_github
            else None
        )
        source_key = f"{source_type}:{source}"
        configured_options = _default_options(
            source, load_options, is_github
        )
        default_label = label_for_profile(configured_options.profile)
        label = st.segmented_control(
            "分析模式",
            [spec.label for spec in PROFILE_SPECS],
            default=default_label,
            selection_mode="single",
            help="；".join(
                f"{spec.label}：{spec.description}"
                for spec in PROFILE_SPECS
            ),
            key=f"profile:{source_key}",
        )
        with st.expander("高级配置"):
            git_labels = list(_GIT_PERIODS)
            git_label = st.selectbox(
                "Git 时间范围",
                git_labels,
                index=git_labels.index(
                    _git_label(configured_options.git_period)
                ),
                help="限制 Git 历史读取范围；范围越小，Git 分析通常越快。",
                key=f"git-period:{source_key}",
            )
            max_file_size_mb = st.number_input(
                "最大文件大小（MB）",
                min_value=0,
                value=_megabytes(configured_options.max_file_size),
                step=1,
                help="单个可读取文本文件的大小上限；0 表示不限制。",
                key=f"max-file-size:{source_key}",
            )
            result_limit = st.number_input(
                "页面结果数量",
                min_value=1,
                value=configured_options.result_limit,
                step=1,
                help="限制页面表格和图表展示数量，不影响完整报告下载。",
                key=f"result-limit:{source_key}",
            )
            reading_limit = st.number_input(
                "阅读与评分数量",
                min_value=1,
                value=configured_options.reading_limit,
                step=1,
                help="限制推荐阅读和评分明细的默认展示数量。",
                key=f"reading-limit:{source_key}",
            )
            include_file_list = st.checkbox(
                "Markdown 包含文件清单",
                value=configured_options.include_file_list,
                help="默认不包含，以避免 Markdown 报告在大型仓库中变得过长。",
                key=f"include-file-list:{source_key}",
            )
        actions = st.columns(2) if is_github else [st]
        actions_disabled = snapshot.active
        submitted = actions[0].form_submit_button(
            "分析仓库",
            type="primary",
            width="stretch",
            disabled=actions_disabled,
        )
        rate_limit_submitted = (
            actions[1].form_submit_button(
                "查询限额",
                width="stretch",
                disabled=actions_disabled,
                help=(
                    "仅读取当前 Token 或公网 IP 的 GitHub Core API "
                    "额度；不读取仓库、不执行分析，且 GitHub 不将"
                    "该端点计入 Core API 额度。"
                ),
            )
            if is_github
            else False
        )
    if rate_limit_submitted:
        if not runtime.snapshot().active:
            clear_github_rate_limit(st.session_state)
            _fetch_rate_limit(st, fetch_rate_limit, runtime)
            _render_rate_limit_result(st)
            return
    if submitted:
        clear_github_rate_limit(st.session_state)
        _start_analysis(
            runtime=runtime,
            source=source,
            reference=reference,
            is_github=is_github,
            label=label or default_label,
            git_label=git_label,
            max_file_size_mb=int(max_file_size_mb),
            result_limit=int(result_limit),
            reading_limit=int(reading_limit),
            include_file_list=include_file_list,
            load_options=load_options,
            ensure_config=ensure_config,
        )
    current = runtime.snapshot()
    if current.active:
        stop = st.button(
            "停止分析",
            disabled=current.state is UiRunState.CANCELLING,
            help="请求后台任务在下一个安全检查点停止，不会强制终止线程。",
            width="content",
        )
        if stop:
            runtime.request_cancel()
    if is_github:
        _render_rate_limit_result(st)
    render_snapshot(runtime.snapshot(), st)


def _default_options(
    source: str, load_options: LoadOptions, is_github: bool = False
) -> AnalysisOptions:
    """读取本地配置或为 GitHub 来源返回默认页面选项。"""
    if is_github:
        return AnalysisOptions()
    try:
        root = Path(source).expanduser().resolve()
        if root.is_dir():
            return load_options(root)
    except (OSError, ValueError):
        pass
    return AnalysisOptions()


def _source_value_for_type(
    source: str,
    previous_type: RepositorySourceType | None,
    is_github: bool,
) -> str:
    """仅在来源类型一致时复用上一次成功分析的输入。"""
    is_previous_github = previous_type is RepositorySourceType.GITHUB
    if source and previous_type is not None:
        if is_github == is_previous_github:
            return source
    return "" if is_github else "."


def _git_label(period: str) -> str:
    """将核心 Git 时间范围转换为页面选项标签。"""
    return next(
        label
        for label, value in _GIT_PERIODS.items()
        if value == period
    )


def _megabytes(size: int | None) -> int:
    """将字节上限转换为页面使用的整数 MB。"""
    return 0 if size is None else ceil(size / (1024 * 1024))


def _fetch_rate_limit(
    st: StreamlitApi,
    fetch_rate_limit: FetchGitHubRateLimit,
    runtime: AnalysisRuntime,
) -> None:
    """执行独立的 GitHub API 额度查询并保留结果。"""
    if runtime.snapshot().active:
        return
    try:
        save_github_rate_limit(st.session_state, fetch_rate_limit())
    except Exception as exc:
        st.error("查询 GitHub API 限额失败。")
        st.caption(str(exc))


def _render_rate_limit_result(st: StreamlitApi) -> None:
    """展示最近一次查询到的 GitHub Core API 额度。"""
    rate_limit = get_github_rate_limit(st.session_state)
    if rate_limit is None:
        return
    st.subheader("GitHub API 额度")
    limit, remaining, reset = st.columns(3)
    limit.metric("限额", rate_limit.limit)
    remaining.metric("剩余", rate_limit.remaining)
    reset.metric(
        "重置时间",
        rate_limit.reset_at.strftime("%Y-%m-%d %H:%M:%S %z"),
    )


def _start_analysis(
    *,
    runtime: AnalysisRuntime,
    source: str,
    reference: str | None,
    is_github: bool,
    label: str,
    git_label: str,
    max_file_size_mb: int,
    result_limit: int,
    reading_limit: int,
    include_file_list: bool,
    load_options: LoadOptions,
    ensure_config: EnsureConfig,
) -> None:
    """解析页面配置并向会话后台运行时提交分析任务。"""
    if runtime.snapshot().active:
        return
    try:
        if is_github:
            analysis_source: Path | RepositorySource = (
                RepositorySource.github(source, reference or None)
            )
            base = AnalysisOptions()
        else:
            root = Path(source).expanduser().resolve()
            if not root.is_dir():
                raise NotADirectoryError(f"仓库目录不存在：{root}")
            ensure_config(root)
            base = load_options(root)
            analysis_source = root
        preset = profile_for_label(label).options()
        options = base.with_overrides(
            profile=preset.profile,
            python_enabled=preset.python_enabled,
            cpp_enabled=preset.cpp_enabled,
            git_enabled=preset.git_enabled,
            dependencies_enabled=preset.dependencies_enabled,
            insights_enabled=preset.insights_enabled,
            git_period=_GIT_PERIODS[git_label],
            max_file_size=None
            if max_file_size_mb == 0
            else max_file_size_mb * 1024 * 1024,
            result_limit=result_limit,
            reading_limit=reading_limit,
            include_file_list=include_file_list,
        )
        runtime.start(
            source=source,
            analysis_source=analysis_source,
            options=options,
        )
    except Exception as exc:
        runtime.record_error(source, exc)
