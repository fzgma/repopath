"""C++ Analyzer 集成测试。"""

from pathlib import Path

from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions

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


def test_cpp_entries_ignore_comments_strings_and_declarations(tmp_path: Path) -> None:
    """入口来自源码定义，注释、字符串和前置声明不产生假入口。"""
    source = (
        "// int main() { return 1; }\n"
        'const char* text = R"tag(\nint wmain() { return 1; }\n)tag";\n'
        "int main();\n"
        "#define ENTRY int wmain() {}\n"
        "int main() { return 0; }\n"
    )
    (tmp_path / "main.cpp").write_text(source, encoding="utf-8")
    report = analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))
    assert [(entry.name, entry.line) for entry in report.cpp.entry_points] == [
        ("main", 7),
    ]


def test_cpp_include_never_replaces_full_path_with_basename(tmp_path: Path) -> None:
    """FileCrypt 的公开头文件不能连到同名的内部实现头文件。"""
    files = {
        "src/cli/main.cpp": "#include <filecrypt/app/operations.hpp>\n",
        "include/filecrypt/app/operations.hpp": "void encrypt();\n",
        "src/app/v1/operations.hpp": "void encrypt_v1();\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    report = analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))
    assert [(edge.source, edge.target) for edge in report.cpp.dependencies] == [
        ("src/cli/main.cpp", "include/filecrypt/app/operations.hpp"),
    ]
