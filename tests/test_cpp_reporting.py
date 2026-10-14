"""C++ 源码依赖的路径证据、条件和报告展示测试。"""

import json
from pathlib import Path

import pytest

from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


@pytest.fixture
def cpp_report(tmp_path: Path) -> RepositoryReport:
    """不提供 SDK 或构建配置，保留各平台分支和无法唯一匹配的引用。"""
    files = {
        "src/main.cpp": (
            "#ifdef _WIN32\n"
            '#include "platform.hpp"\n'
            "int wmain() { return 0; }\n"
            "#else\n"
            "#include <api/public.hpp>\n"
            "int main() { return 0; }\n"
            "#endif\n"
            "#include <shared.hpp>\n"
            "#include <vendor/shared.hpp>\n"
            "#include HEADER_MACRO\n"
        ),
        "src/platform.hpp": "struct Platform {};\n",
        "include/api/public.hpp": "void run();\n",
        "first/shared.hpp": "struct First {};\n",
        "second/shared.hpp": "struct Second {};\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))


def test_json_preserves_include_evidence_and_platform_entries(
    cpp_report: RepositoryReport,
) -> None:
    """引用位置、匹配理由与未解析项都保留，互斥入口不合并。"""
    payload = json.loads(JsonRenderer().render(cpp_report))
    cpp = payload["cpp"]
    assert cpp["status"] == "completed"
    assert cpp["file_count"] == 5
    details = {item["name"]: item for item in cpp["include_details"]}
    local = details["platform.hpp"]
    assert local["source"] == "src/main.cpp"
    assert local["line"] == 2
    assert local["kind"] == "quoted"
    assert local["target"] == "src/platform.hpp"
    assert local["resolution"] == "relative"
    assert "_WIN32" in " ".join(local["conditions"])
    assert details["api/public.hpp"]["target"] == "include/api/public.hpp"
    assert details["api/public.hpp"]["resolution"] == "suffix"
    assert details["shared.hpp"]["target"] is None
    assert details["shared.hpp"]["resolution"] == "ambiguous"
    assert details["shared.hpp"]["candidates"] == [
        "first/shared.hpp", "second/shared.hpp",
    ]
    assert details["vendor/shared.hpp"]["resolution"] == "unresolved"
    assert details["HEADER_MACRO"]["resolution"] == "macro"
    entries = {entry["name"]: entry for entry in cpp["entry_points"]}
    assert set(entries) == {"main", "wmain"}
    assert entries["main"]["line"] == 6
    assert entries["wmain"]["line"] == 3
    assert entries["main"]["conditions"] != entries["wmain"]["conditions"]
    assert str(cpp_report.repository.root) not in json.dumps(cpp)


def test_ambiguous_and_missing_includes_do_not_create_graph_edges(
    cpp_report: RepositoryReport,
) -> None:
    """阅读依赖仅使用唯一匹配，不把多个候选或缺失路径猜成依赖。"""
    assert {edge.target for edge in cpp_report.cpp.dependencies} == {
        "src/platform.hpp", "include/api/public.hpp",
    }
    assert {edge.target for edge in cpp_report.dependencies.edges} == {
        "cpp:src/platform.hpp", "cpp:include/api/public.hpp",
    }
    assert cpp_report.insights.reading_order


@pytest.mark.parametrize("detail", ["full", "summary"])
def test_markdown_explains_conditions_candidates_and_missing_paths(
    cpp_report: RepositoryReport, detail: str,
) -> None:
    """完整与摘要报告均说明静态路径匹配的边界，不隐藏未解析项。"""
    markdown = MarkdownRenderer().render(cpp_report, detail=detail)
    assert "C++ Include 路径匹配" in markdown
    assert "多个候选" in markdown
    assert "first/shared.hpp" in markdown
    assert "second/shared.hpp" in markdown
    assert "vendor/shared.hpp" in markdown
    assert "HEADER_MACRO" in markdown
    assert "条件不求值" in markdown
    assert "_WIN32" in markdown
    assert "wmain" in markdown
    includes = markdown.split("### C++ Include 路径匹配", 1)[1]
    assert str(cpp_report.repository.root) not in includes


def test_markdown_limits_details_but_json_keeps_every_include(
    cpp_report: RepositoryReport,
) -> None:
    """面向阅读的列表可截断，机器可读证据保持完整。"""
    cpp_report.options = cpp_report.options.with_overrides(result_limit=1)
    markdown = MarkdownRenderer().render(cpp_report)
    payload = json.loads(JsonRenderer().render(cpp_report))
    assert "其余 4 处省略" in markdown
    assert len(payload["cpp"]["include_details"]) == 5


def test_markdown_keeps_nested_condition_precedence(tmp_path: Path) -> None:
    """嵌套的或条件与外层条件组合时保持原有边界。"""
    (tmp_path / "main.cpp").write_text(
        '#if A || B\n#if C\n#include "api.hpp"\n#endif\n#endif\n',
        encoding="utf-8",
    )
    report = analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))
    markdown = MarkdownRenderer().render(report)
    assert r"(A \|\| B) && (C)" in markdown
