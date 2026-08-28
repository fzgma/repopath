"""RepoPath Streamlit 根目录入口。"""

from importlib import import_module
from typing import Any, cast

from repopath.core.config import (
    ensure_default_config,
    load_analysis_options,
)
from repopath.core.service import (
    analyze_repository,
    fetch_github_rate_limit,
)
from repopath.interface.ui import (
    render_analysis_progress,
    render_application,
)


def main() -> None:
    """配置 Streamlit 页面并交给 UI 包执行交互流程。"""
    try:
        st = cast(Any, import_module("streamlit"))
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "缺少 Streamlit，请先执行："
            "python.exe -m pip install -r requirements.txt"
        ) from exc
    st.set_page_config(page_title="RepoPath", layout="wide")

    active = render_application(
        st,
        analyze_repository,
        load_analysis_options,
        ensure_default_config,
        fetch_github_rate_limit,
    )
    if active:

        @st.fragment(run_every=0.5)
        def render_progress() -> None:
            """定时刷新后台分析进度并在完成后刷新页面。"""
            render_analysis_progress(st, analyze_repository)

        render_progress()


if __name__ == "__main__":
    main()
