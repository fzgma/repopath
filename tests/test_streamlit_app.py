"""Streamlit 页面边界测试。"""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_running_an_analysis() -> None:
    """验证页面初始状态可以加载且不会自动扫描仓库。"""
    app_path = Path(__file__).parents[1] / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "RepoPath"
    assert app.info[0].value == "输入本地仓库路径后开始分析。"


def test_streamlit_app_renders_a_deep_analysis() -> None:
    """验证深度分析可以渲染全部结果页签且不产生页面异常。"""
    root = Path(__file__).parents[1]
    fixture = root / "tests" / "fixtures" / "mixed_repo"
    app = AppTest.from_file(str(root / "app.py")).run(timeout=10)

    app.text_input[0].set_value(str(fixture))
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
