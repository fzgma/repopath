"""C++ 语义报告、覆盖边界和源码位置契约测试。"""

import json
from pathlib import Path

import pytest

from repopath.core.service import analyze_repository
from repopath.model.cpp import (
    CppAnalysis,
    CppCoverage,
    CppDiagnostic,
    CppDirectCall,
    CppFileAnalysis,
    CppLocation,
    CppSemanticSymbol,
    CppTranslationUnit,
)
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository, RepositorySource
from repopath.model.result import AnalysisResult, AnalyzerName, AnalyzerStatus
from repopath.model.source import SourceSymbol
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


def _semantic_report(root: Path) -> RepositoryReport:
    """构造带跨文件定义、调用和部分覆盖的报告。"""
    caller = CppSemanticSymbol(
        usr="c:@F@main#", name="main", qualified_name="main",
        kind="function", type_spelling="int ()",
        definitions=[CppLocation(root / "main.cpp", 2, 5)],
    )
    callee = CppSemanticSymbol(
        usr="c:@N@demo@F@answer#", name="answer", qualified_name="demo::answer",
        kind="function", type_spelling="int ()",
        declarations=[CppLocation(root / "api.hpp", 1, 22)],
        definitions=[CppLocation(root / "api.cpp", 2, 22)],
    )
    external = root.parent / "external-toolchain" / "missing.hpp"
    cpp = CppAnalysis(
        backend="libclang", analysis_level="semantic", semantic_status="partial",
        semantic_reason=f"部分编译单元未完成：{root / 'broken.cpp'}",
        compile_commands=root / "build" / "compile_commands.json",
        library_version="clang version 18.1.1",
        symbols={caller.usr: caller, callee.usr: callee},
        calls=[CppDirectCall(
            caller_usr=caller.usr, callee_usr=callee.usr,
            location=CppLocation(root / "main.cpp", 2, 21),
            translation_units=[root / "main.cpp"],
        )],
        translation_units=[
            CppTranslationUnit(
                path=root / "main.cpp", directory=root,
                arguments=("clang++", "-c", "main.cpp"), status="completed",
            ),
            CppTranslationUnit(
                path=root / "broken.cpp", directory=root,
                arguments=("clang++", "-c", "broken.cpp"), status="partial",
                reason="头文件缺失",
            ),
        ],
        diagnostics=[CppDiagnostic(
            severity="error", message=f"找不到 {external}",
            translation_unit=root / "broken.cpp", path=external, line=3, column=1,
        )],
        coverage=CppCoverage(
            total_files=4, covered_files=3, total_translation_units=2,
            parsed_translation_units=2, failed_translation_units=0,
            uncovered_files=[root / "broken.cpp"],
        ),
    )
    cpp.files[root / "main.cpp"] = CppFileAnalysis(
        path=root / "main.cpp",
        functions=[SourceSymbol("main", "function", root / "main.cpp", 2)],
    )
    return RepositoryReport(
        repository=Repository.from_path(root),
        options=AnalysisOptions(cpp_backend="libclang"),
        cpp=cpp,
        analyzer_results={AnalyzerName.CPP: AnalysisResult(AnalyzerName.CPP)},
    )


def test_json_keeps_basic_projection_and_exposes_semantic_evidence(tmp_path: Path) -> None:
    """验证旧符号投影保留，调用端点和跨文件位置可以追溯。"""
    report = _semantic_report(tmp_path)
    cpp = json.loads(JsonRenderer().render(report))["cpp"]

    assert cpp["backend"] == "libclang"
    assert cpp["analysis_level"] == "semantic"
    assert cpp["status"] == "completed"
    assert cpp["semantic_status"] == "partial"
    assert cpp["compile_commands"] == "build/compile_commands.json"
    assert cpp["coverage"]["uncovered_files"] == ["broken.cpp"]
    assert cpp["symbols"] == [
        {"path": "main.cpp", "name": "main", "kind": "function", "line": 2}
    ]
    symbols = {item["usr"]: item for item in cpp["semantic_symbols"]}
    call = cpp["direct_calls"][0]
    assert symbols[call["caller_usr"]]["qualified_name"] == "main"
    target = symbols[call["callee_usr"]]
    assert target["declarations"][0]["path"] == "api.hpp"
    assert target["definitions"][0]["path"] == "api.cpp"
    assert call["location"] == {"path": "main.cpp", "line": 2, "column": 21}
    assert call["translation_units"] == ["main.cpp"]
    assert "arguments" not in cpp["translation_units"][0]
    assert cpp["diagnostics"][0]["path"] == "[external]/missing.hpp"
    assert str(tmp_path.parent / "external-toolchain") not in cpp["diagnostics"][0]["message"]


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_markdown_shows_partial_coverage_definitions_and_calls(
    tmp_path: Path, detail: str,
) -> None:
    """摘要和完整报告均展示实际后端、部分覆盖与关键定位证据。"""
    report = _semantic_report(tmp_path)
    markdown = MarkdownRenderer().render(report, detail=detail)

    assert "## C++ 语义分析" in markdown
    assert "`libclang`" in markdown and "`partial`" in markdown
    assert "语义覆盖文件：3 / 4" in markdown
    assert "demo::answer" in markdown
    assert "api.cpp:2:22" in markdown
    assert "main.cpp:2:21" in markdown
    assert "### 直接调用" in markdown
    assert "### 语义诊断" in markdown
    assert "[external]/missing.hpp" in markdown
    assert "不计入现有模块依赖评分" in markdown


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_failed_semantic_report_preserves_diagnostics(tmp_path: Path, detail: str) -> None:
    """Analyzer 失败不能吞掉语义覆盖和失败原因。"""
    report = _semantic_report(tmp_path)
    report.cpp.semantic_status = "failed"
    report.cpp.semantic_reason = "没有可用编译单元"
    report.analyzer_results[AnalyzerName.CPP] = AnalysisResult(
        AnalyzerName.CPP, status=AnalyzerStatus.FAILED, reason="语义分析失败",
    )
    markdown = MarkdownRenderer().render(report, detail=detail)
    section = markdown.split("## C++ 语义分析", 1)[1].split("\n## ", 1)[0]

    assert "`failed`" in section
    assert "没有可用编译单元" in section
    assert "### 语义诊断" in section
    assert "当前没有检测到 C++" not in markdown


def test_snapshot_paths_are_not_exposed_in_semantic_reports(tmp_path: Path) -> None:
    """GitHub 快照的临时根目录不会出现在 JSON 或 Markdown。"""
    report = _semantic_report(tmp_path)
    report.source = RepositorySource.github("https://github.com/example/demo", "a" * 40)
    report.errors.append(f"语义分析失败：{tmp_path / 'broken.cpp'}")
    payload = JsonRenderer().render(report)
    markdown = MarkdownRenderer().render(report)

    assert json.dumps(str(tmp_path))[1:-1] not in payload
    assert tmp_path.as_posix() not in payload
    assert str(tmp_path) not in markdown
    assert tmp_path.as_posix() not in markdown
    assert json.loads(payload)["repository"]["root"] == report.source.location


def test_basic_report_does_not_claim_semantic_analysis() -> None:
    """默认基础分析仍保留 include 图，并明确语义能力未请求。"""
    fixture = Path(__file__).parent / "fixtures" / "mixed_repo"
    report = analyze_repository(fixture, options=AnalysisOptions(git_enabled=False))
    cpp = json.loads(JsonRenderer().render(report))["cpp"]

    assert cpp["backend"] == "basic"
    assert cpp["semantic_status"] == "not_requested"
    assert cpp["semantic_symbols"] == cpp["direct_calls"] == []
    assert cpp["symbols"] and cpp["dependencies"]
    assert "## C++ 语义分析" not in MarkdownRenderer().render(report)


def test_libclang_report_links_cross_file_calls_without_changing_graph(tmp_path: Path) -> None:
    """以真实 libclang 验证跨文件调用证据不混入 include 评分图。"""
    pytest.importorskip("clang.cindex")
    (tmp_path / "api.hpp").write_text(
        "namespace demo { int answer(); }\n", encoding="utf-8",
    )
    (tmp_path / "api.cpp").write_text(
        '#include "api.hpp"\nnamespace demo { int answer() { return 42; } }\n',
        encoding="utf-8",
    )
    (tmp_path / "main.cpp").write_text(
        '#include "api.hpp"\nint main() { return demo::answer(); }\n',
        encoding="utf-8",
    )
    commands = [
        {
            "directory": str(tmp_path), "file": name,
            "arguments": ["clang++", "-std=c++17", "-I", str(tmp_path), "-c", name],
        }
        for name in ("api.cpp", "main.cpp")
    ]
    (tmp_path / "compile_commands.json").write_text(json.dumps(commands), encoding="utf-8")
    basic = analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))
    semantic = analyze_repository(
        tmp_path, options=AnalysisOptions(cpp_backend="libclang", git_enabled=False),
    )
    cpp = json.loads(JsonRenderer().render(semantic))["cpp"]

    assert cpp["status"] == cpp["semantic_status"] == "completed"
    assert cpp["coverage"]["parsed_translation_units"] == 2
    symbols = {item["usr"]: item for item in cpp["semantic_symbols"]}
    targets = [item for item in symbols.values() if item["qualified_name"] == "demo::answer"]
    assert len(targets) == 1
    assert {item["path"] for item in targets[0]["definitions"]} == {"api.cpp"}
    assert any(call["callee_usr"] == targets[0]["usr"] for call in cpp["direct_calls"])
    assert semantic.dependencies.edges == basic.dependencies.edges
    assert all(edge.kind != "call" for edge in semantic.dependencies.edges)
