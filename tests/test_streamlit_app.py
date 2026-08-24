"""Streamlit 页面边界测试。"""

from pathlib import Path
from shutil import copytree

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_running_an_analysis() -> None:
    """验证页面初始状态可以加载且不会自动扫描仓库。"""
    app_path = Path(__file__).parents[1] / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "RepoPath"
    assert (
        app.info[0].value
        == "输入本地目录或 GitHub 公开仓库地址后开始分析。"
    )


def test_streamlit_app_renders_a_deep_analysis(tmp_path: Path) -> None:
    """验证深度分析可以渲染全部结果页签且不产生页面异常。"""
    root = Path(__file__).parents[1]
    fixture = tmp_path / "mixed_repo"
    copytree(root / "tests" / "fixtures" / "mixed_repo", fixture)
    app = AppTest.from_file(str(root / "app.py")).run(timeout=10)

    app.text_input[0].set_value(str(fixture))
    app.run(timeout=10)
    app.button[0].click()
    app.run(timeout=30)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "概览",
        "推荐阅读",
        "依赖关系",
        "Python",
        "C++",
        "Git",
        "报告",
    ]
    assert len(app.metric) >= 6


def test_streamlit_app_shows_rate_limit_query_for_github_only() -> None:
    """验证查询限额按钮只在 GitHub 来源模式中显示。"""
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=10)

    assert "查询限额" not in [button.label for button in app.button]
    app.segmented_control[0].set_value("GitHub 公开仓库")
    app.run(timeout=10)

    assert "查询限额" in [button.label for button in app.button]


def test_streamlit_app_reads_repository_config_into_advanced_settings(
    tmp_path: Path,
) -> None:
    """验证切换仓库后 UI 会用配置文件填充高级设置。"""
    root = Path(__file__).parents[1]
    (tmp_path / ".repopath.toml").write_text(
        """
[scan]
profile = "standard"
max_file_size = 3145728

[git]
period = "90"

[report]
limit = 12
reading_limit = 4
include_file_list = true
""".strip(),
        encoding="utf-8",
    )
    app = AppTest.from_file(str(root / "app.py")).run(timeout=10)

    app.text_input[0].set_value(str(tmp_path))
    app.run(timeout=10)

    assert not app.exception
    assert app.segmented_control[0].value == "本地目录"
    assert app.segmented_control[1].value == "标准"
    assert app.selectbox[0].value == "最近 90 天"
    assert [item.value for item in app.number_input] == [3, 12, 4]
    assert app.checkbox[0].value is True
