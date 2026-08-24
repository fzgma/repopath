"""Python Analyzer 集成测试。"""

from pathlib import Path

from repopath.core.service import analyze_repository


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mixed_repo"


def test_python_analysis_extracts_symbols_dependencies_and_entry_point() -> None:
    """验证 Python 分析可识别符号、依赖和主程序入口。"""
    report = analyze_repository(FIXTURE_ROOT)

    assert len(report.python.entry_points) == 1
    assert report.repository.relative_path(report.python.entry_points[0].path) == "python_app.py"
    assert any(edge.source == "python_app" and edge.target == "helpers" for edge in report.python.dependencies)
    assert report.python.function_count == 5
    assert report.python.class_count == 1
    assert any(module.name == "helpers" for module in report.python.core_modules)
    assert any(edge.source == "pkg.consumer" and edge.target == "pkg.mod" for edge in report.python.dependencies)
