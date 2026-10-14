"""真实 libclang 跨 TU 语义、质量证据与可选依赖行为测试。"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from repopath.analyzer.cpp import semantics
from repopath.analyzer.cpp.semantics import load_libclang
from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions
from repopath.model.result import AnalyzerName, AnalyzerStatus


@pytest.fixture
def native_libclang() -> None:
    """专用语义 CI 必须实际加载原生库，普通 base 测试可明确跳过。"""
    if importlib.util.find_spec("clang") is None:
        if os.environ.get("REPOPATH_REQUIRE_LIBCLANG") == "1":
            pytest.fail("专用语义测试要求安装 libclang")
        pytest.skip("未安装可选 libclang")
    load_libclang()


def _write_project(root: Path, main: str | None = None) -> Path:
    """生成无系统头依赖、含重载声明和定义的两个 TU。"""
    (root / "include").mkdir()
    (root / "src").mkdir()
    build = root / "build dir"
    build.mkdir()
    (root / "include" / "api.hpp").write_text(
        "#pragma once\n#ifndef ENABLED\n#error missing define\n#endif\n"
        "namespace demo { int choose(int); double choose(double); }\n",
        encoding="utf-8",
    )
    (root / "src" / "api.cpp").write_text(
        '#include "api.hpp"\n'
        "int demo::choose(int value) { return value + 1; }\n"
        "double demo::choose(double value) { return value + 0.5; }\n",
        encoding="utf-8",
    )
    (root / "src" / "main.cpp").write_text(
        main or '#include "api.hpp"\nint main() { return demo::choose(1); }\n',
        encoding="utf-8",
    )
    path = build / "compile_commands.json"
    path.write_text(
        json.dumps(
            [
                {
                    "directory": str(build),
                    "file": f"../src/{name}",
                    "arguments": [
                        "clang++",
                        "-std=c++17",
                        "-I../include",
                        "-DENABLED=1",
                        "-c",
                        f"../src/{name}",
                        "-o",
                        f"{name}.o",
                    ],
                }
                for name in ("api.cpp", "main.cpp")
            ]
        ),
        encoding="utf-8",
    )
    return path


def _options(database: Path | None = None, **kwargs: object) -> AnalysisOptions:
    """只启用本任务所需后端，保留正常流水线聚合。"""
    return AnalysisOptions(
        cpp_backend="libclang",
        cpp_compile_commands=str(database) if database else None,
        git_enabled=False,
    ).with_overrides(**kwargs)


def test_missing_database_is_a_failure_without_basic_fallback(tmp_path: Path) -> None:
    """缺少编译配置时明确失败，不以基础扫描掩盖请求的语义分析。"""
    (tmp_path / "main.cpp").write_text("int main() { return 0; }", encoding="utf-8")
    report = analyze_repository(tmp_path, options=_options())
    assert report.analyzer_results[AnalyzerName.CPP].status == AnalyzerStatus.FAILED
    assert report.cpp.backend == "libclang"
    assert report.cpp.semantic_status == "failed"
    assert "compile_commands.json" in (report.cpp.semantic_reason or "")
    assert not report.cpp.files


def test_unavailable_native_library_is_an_explicit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合法编译配置下的库加载失败必须暴露，不能产生基础扫描假成功。"""
    database = _write_project(tmp_path)

    def unavailable_library() -> None:
        """模拟打包遗漏原生库时的初始化错误。"""
        raise RuntimeError("libclang 包内 native 库缺失")

    monkeypatch.setattr(semantics, "load_libclang", unavailable_library)

    report = analyze_repository(tmp_path, options=_options(database))

    assert report.analyzer_results[AnalyzerName.CPP].status == AnalyzerStatus.FAILED
    assert report.cpp.backend == "libclang"
    assert report.cpp.semantic_status == "failed"
    assert "native 库缺失" in (report.cpp.semantic_reason or "")
    assert report.cpp.coverage.total_translation_units == 2
    assert report.cpp.coverage.parsed_translation_units == 0
    assert not report.cpp.files
    assert not report.cpp.symbols


def test_usr_merges_declarations_definitions_and_binds_overloads(
    tmp_path: Path,
    native_libclang: None,
) -> None:
    """以稳定 USR 合并跨文件定义，并将重载调用绑定到正确签名。"""
    database = _write_project(tmp_path)
    before = Path.cwd()
    report = analyze_repository(tmp_path, options=_options(database))
    assert Path.cwd() == before
    assert report.analyzer_results[AnalyzerName.CPP].status == AnalyzerStatus.COMPLETED
    cpp = report.cpp
    assert cpp.semantic_status == "completed", cpp.diagnostics
    assert cpp.library_version and "clang" in cpp.library_version
    overloads = [
        symbol
        for symbol in cpp.symbols.values()
        if symbol.qualified_name == "demo::choose"
    ]
    assert len(overloads) == 2
    assert len({symbol.usr for symbol in overloads}) == 2
    assert all(
        len(symbol.declarations) == 2 and len(symbol.definitions) == 1
        for symbol in overloads
    )
    assert len(cpp.calls) == 1
    call = cpp.calls[0]
    assert cpp.symbols[call.caller_usr].name == "main"
    assert cpp.symbols[call.callee_usr].type_spelling == "int (int)"
    assert (
        cpp.symbols[call.callee_usr].definitions[0].path == tmp_path / "src" / "api.cpp"
    )
    assert call.location.path == tmp_path / "src" / "main.cpp"
    assert call.translation_units == [tmp_path / "src" / "main.cpp"]
    assert cpp.coverage.total_files == cpp.coverage.covered_files == 3
    assert cpp.coverage.parsed_translation_units == 2
    assert {(edge.source, edge.target) for edge in cpp.dependencies} == {
        ("src/api.cpp", "include/api.hpp"),
        ("src/main.cpp", "include/api.hpp"),
    }
    assert len(cpp.entry_points) == 1


def test_errors_and_uncompiled_files_are_partial_not_empty_success(
    tmp_path: Path,
    native_libclang: None,
) -> None:
    """保留可解析文件的事实，并暴露出错和未编译文件的覆盖缺口。"""
    database = _write_project(
        tmp_path, '#include "missing.hpp"\nint main(){return 0;}\n'
    )
    (tmp_path / "src" / "uncompiled.cpp").write_text(
        "int unused(){return 1;}", encoding="utf-8"
    )
    report = analyze_repository(tmp_path, options=_options(database))
    assert report.analyzer_results[AnalyzerName.CPP].status == AnalyzerStatus.COMPLETED
    assert report.cpp.semantic_status == "partial"
    assert any(
        diagnostic.severity in {"error", "fatal"}
        for diagnostic in report.cpp.diagnostics
    )
    assert report.cpp.coverage.covered_files == 2
    assert set(report.cpp.coverage.uncovered_files) == {
        tmp_path / "src" / "main.cpp",
        tmp_path / "src" / "uncompiled.cpp",
    }
    assert not report.cpp.calls
    assert not report.cpp.entry_points
    assert any(
        symbol.qualified_name == "demo::choose"
        for symbol in report.cpp.symbols.values()
    )


def test_only_direct_evaluated_body_calls_are_emitted(
    tmp_path: Path,
    native_libclang: None,
) -> None:
    """排除动态分派、间接调用、未求值表达式和内部链接实体。"""
    source = """
#include "api.hpp"
struct Base { virtual int run() { return 0; } int direct() { return 0; } };
int other(int value = demo::choose(1)) { return value; }
static int local() { return 0; }
int calls(Base& object, int (*pointer)(int)) {
    int size = sizeof(demo::choose(1));
    using Type = decltype(demo::choose(1));
    decltype(demo::choose(1)) item;
    bool safe = noexcept(demo::choose(1));
    auto closure = [] { return demo::choose(1); };
    object.run(); pointer(1); local();
    return object.direct() + demo::choose(1);
}
int main() { return 0; }
"""
    database = _write_project(tmp_path, source)
    report = analyze_repository(tmp_path, options=_options(database))
    cpp = report.cpp
    assert cpp.semantic_status == "completed", cpp.diagnostics
    assert [
        (cpp.symbols[call.caller_usr].name, cpp.symbols[call.callee_usr].name)
        for call in cpp.calls
    ] == [
        ("calls", "direct"),
        ("calls", "choose"),
    ]
    assert all(symbol.name != "local" for symbol in cpp.symbols.values())


def test_scan_exclusions_limit_facts_and_coverage(
    tmp_path: Path,
    native_libclang: None,
) -> None:
    """扫描排除项同时约束语义事实和覆盖统计。"""
    database = _write_project(tmp_path)
    report = analyze_repository(
        tmp_path, options=_options(database, excluded_patterns=("src/api.cpp",))
    )
    assert report.cpp.semantic_status == "partial"
    assert report.cpp.coverage.total_files == 2
    assert report.cpp.coverage.covered_files == 2
    assert all(
        location.path.name != "api.cpp"
        for symbol in report.cpp.symbols.values()
        for location in symbol.definitions
    )
    assert any(unit.status == "skipped" for unit in report.cpp.translation_units)


def test_local_class_field_initializer_is_not_an_enclosing_function_call(
    tmp_path: Path,
    native_libclang: None,
) -> None:
    """仅声明局部类不执行成员初始化，不能把其中调用归到外围函数。"""
    database = _write_project(
        tmp_path,
        "int helper() { return 1; }\n"
        "int main() { struct Local { int value = helper(); }; return 0; }\n",
    )

    report = analyze_repository(tmp_path, options=_options(database))

    assert report.cpp.semantic_status == "completed", report.cpp.diagnostics
    assert not report.cpp.calls


def test_all_rejected_commands_fail_instead_of_silently_succeeding(
    tmp_path: Path,
    native_libclang: None,
) -> None:
    """所有编译条目都不可用时，不返回空的成功结果。"""
    database = _write_project(tmp_path)
    records = json.loads(database.read_text(encoding="utf-8"))
    for record in records:
        record["arguments"].append("--config=untrusted.cfg")
    database.write_text(json.dumps(records), encoding="utf-8")
    report = analyze_repository(tmp_path, options=_options(database))
    assert report.analyzer_results[AnalyzerName.CPP].status == AnalyzerStatus.FAILED
    assert report.cpp.semantic_status == "failed"
    assert report.cpp.coverage.failed_translation_units == 2
    assert not report.cpp.symbols


def test_libclang_does_not_accept_disabled_compatibility_checks(
    native_libclang: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不接受进程内其他调用者关闭绑定与原生库的兼容性检查。"""
    from clang import cindex

    monkeypatch.setattr(cindex.Config, "compatibility_check", False)
    with pytest.raises(RuntimeError, match="兼容性检查"):
        load_libclang()
