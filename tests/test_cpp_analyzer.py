"""C++ Analyzer 集成测试。"""

from pathlib import Path

from repopath.core.service import analyze_repository


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mixed_repo"


def test_cpp_analysis_extracts_includes_symbols_and_main() -> None:
    """验证 C++ 分析可识别 include、符号和 main 入口。"""
    report = analyze_repository(FIXTURE_ROOT)

    assert len(report.cpp.files) == 3
    assert report.cpp.include_counts["greeting.hpp"] == 2
    assert report.cpp.function_count >= 2
    assert report.cpp.type_count == 1
    assert report.cpp.namespace_count >= 2
    assert len(report.cpp.entry_points) == 1
    assert (
        report.repository.relative_path(report.cpp.entry_points[0].path)
        == "src/main.cc"
    )
    assert any(
        edge.target == "include/greeting.hpp"
        for edge in report.cpp.dependencies
    )
