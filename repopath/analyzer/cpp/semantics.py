"""通过随 PyPI libclang 分发的库提取跨翻译单元的有限语义事实。"""

import sys
from pathlib import Path
from threading import Lock
from typing import Any, cast

from ...core.context import AnalysisContext
from ...core.control import AnalysisCancelled
from ...model.cpp import (
    CppAnalysis,
    CppDiagnostic,
    CppDirectCall,
    CppFileAnalysis,
    CppLocation,
    CppSemanticSymbol,
    CppTranslationUnit,
)
from ...model.language import Language
from ...model.result import AnalysisResult, AnalysisState, AnalyzerName
from ...model.source import SourceDependency, SourceSymbol
from .compilation import find_compilation_database, read_compilation_database

_LIBRARY_LOCK = Lock()


def load_libclang() -> tuple[Any, Any, str]:
    """只加载 Python 包内 native 库，拒绝系统替换及关闭兼容性检查。"""
    try:
        from clang import cindex
    except ImportError as exc:
        raise RuntimeError(
            "libclang 后端不可用：请安装配套的 PyPI libclang 依赖"
        ) from exc
    filename = (
        "libclang.dll"
        if sys.platform == "win32"
        else "libclang.dylib"
        if sys.platform == "darwin"
        else "libclang.so"
    )
    native = (Path(cindex.__file__).resolve().parent / "native" / filename).resolve()
    if not native.is_file():
        raise RuntimeError("libclang 包内 native 库缺失；不会回退加载系统 libclang")
    with _LIBRARY_LOCK:
        if not cindex.Config.compatibility_check:
            raise RuntimeError("libclang 兼容性检查已被关闭；拒绝使用该全局配置")
        if cindex.Config.loaded:
            loaded_library = cast(Any, cindex.conf.lib)
            if Path(loaded_library._name).resolve() != native:
                raise RuntimeError("已加载其他 libclang；需要新进程使用包内配套库")
        else:
            cindex.Config.set_library_file(str(native))
        index = cindex.Index.create()
        library = cast(Any, cindex.conf.lib)
        version_function = library.clang_getClangVersion
        version_function.restype = cindex._CXString
        version_function.errcheck = cindex._CXString.from_result
        version = version_function()
    return cindex, index, version


def _location(cursor: Any) -> CppLocation | None:
    """将 Clang 光标的位置转换为与第三方实现无关的领域对象。"""
    location = cursor.location
    if location.file is None:
        return None
    return CppLocation(
        Path(location.file.name).resolve(), location.line, location.column
    )


def _qualified_name(cursor: Any) -> str:
    """由语义父节点生成限定名，不以裸名称合并符号。"""
    parts = [cursor.spelling]
    parent = cursor.semantic_parent
    while parent is not None and parent.kind.name != "TRANSLATION_UNIT":
        if parent.spelling:
            parts.append(parent.spelling)
        parent = parent.semantic_parent
    return "::".join(reversed(parts))


def _add_symbol(analysis: CppAnalysis, cursor: Any, allowed: set[Path]) -> str | None:
    """将项目符号加入 USR 索引，并保存去重后的声明和定义位置。"""
    location = _location(cursor)
    if location is None or location.path not in allowed:
        return None
    if cursor.linkage.name == "INTERNAL":
        # 内部链接实体在不同 TU 的 USR 可能相同，POC 保守排除以免错误归并。
        return None
    usr = cursor.get_usr()
    if not usr:
        return None
    kind = cursor.kind.name.lower()
    symbol = analysis.symbols.setdefault(
        usr,
        CppSemanticSymbol(
            usr, cursor.spelling, _qualified_name(cursor), kind, cursor.type.spelling
        ),
    )
    if location not in symbol.declarations:
        symbol.declarations.append(location)
    if cursor.is_definition() and location not in symbol.definitions:
        symbol.definitions.append(location)
    return usr


def _extract_unit(
    context: AnalysisContext,
    unit: CppTranslationUnit,
    translation_unit: Any,
    allowed: set[Path],
) -> CppAnalysis:
    """从无错误的 TU 提取项目符号、确定调用和实际 include 关系。"""
    result = CppAnalysis()
    result.files[unit.path] = CppFileAnalysis(unit.path)
    function_kinds = {
        "FUNCTION_DECL",
        "CXX_METHOD",
        "CONSTRUCTOR",
        "DESTRUCTOR",
        "CONVERSION_FUNCTION",
        "FUNCTION_TEMPLATE",
    }
    type_kinds = {"CLASS_DECL", "STRUCT_DECL", "ENUM_DECL", "CLASS_TEMPLATE"}
    symbol_kinds = function_kinds | type_kinds | {"NAMESPACE"}
    stack: list[tuple[Any, str | None]] = [(translation_unit.cursor, None)]
    while stack:
        context.cancellation.raise_if_cancelled()
        cursor, caller = stack.pop()
        location = _location(cursor)
        if location is not None and location.path not in allowed:
            continue
        kind = cursor.kind.name
        if kind in {
            "LAMBDA_EXPR",
            "CXX_UNARY_EXPR",
            "CXX_TYPEID_EXPR",
            "TYPE_ALIAS_DECL",
            "TYPEDEF_DECL",
            "STATIC_ASSERT",
            "REQUIRES_EXPR",
        }:
            # 闭包与未求值表达式不能归属为外围函数中的确定调用。
            continue
        if kind == "VAR_DECL":
            # decltype 类型中也可能出现 CALL_EXPR；POC 保守略过整个此类声明。
            prefix = []
            for token in cursor.get_tokens():
                if token.spelling == "=":
                    break
                prefix.append(token.spelling)
            if "decltype" in prefix:
                continue
        if location is not None:
            item = result.files.setdefault(
                location.path, CppFileAnalysis(location.path)
            )
            if kind in symbol_kinds:
                usr = _add_symbol(result, cursor, allowed)
                projected = SourceSymbol(
                    cursor.spelling, kind.lower(), location.path, location.line
                )
                if kind in function_kinds:
                    caller = usr
                    if projected not in item.functions:
                        item.functions.append(projected)
                    if (
                        kind == "FUNCTION_DECL"
                        and cursor.spelling == "main"
                        and cursor.is_definition()
                        and cursor.semantic_parent.kind.name == "TRANSLATION_UNIT"
                    ):
                        result.entry_points.append(projected)
                elif kind in type_kinds:
                    if projected not in item.types:
                        item.types.append(projected)
                elif projected not in item.namespaces:
                    item.namespaces.append(projected)
            if kind == "CALL_EXPR" and caller:
                target = cursor.referenced
                if target is not None and target.kind.name in function_kinds:
                    virtual = (
                        target.kind.name in {"CXX_METHOD", "DESTRUCTOR"}
                        and target.is_virtual_method()
                    )
                    if not virtual:
                        callee = _add_symbol(result, target, allowed)
                        if callee:
                            result.calls.append(
                                CppDirectCall(caller, callee, location, [unit.path])
                            )
        for child in reversed(list(cursor.get_children())):
            child_caller = caller
            if kind in type_kinds or (
                kind in function_kinds
                and child.kind.name not in {"COMPOUND_STMT", "CXX_TRY_STMT"}
            ):
                # 类型声明、参数默认值与返回类型不属于外围函数的执行体。
                # 类成员方法在遍历到自身时重新确定调用方。
                child_caller = None
            stack.append((child, child_caller))
    for inclusion in translation_unit.get_includes():
        if inclusion.source is None:
            continue
        source = Path(inclusion.source.name).resolve()
        target = Path(inclusion.include.name).resolve()
        if source not in allowed:
            continue
        item = result.files.setdefault(source, CppFileAnalysis(source))
        display = (
            context.repository.relative_path(target)
            if target in allowed
            else target.name
        )
        if display not in item.includes:
            item.includes.append(display)
        if target in allowed:
            result.files.setdefault(target, CppFileAnalysis(target))
            dependency = SourceDependency(
                context.repository.relative_path(source),
                context.repository.relative_path(target),
                "include",
            )
            if dependency not in result.dependencies:
                result.dependencies.append(dependency)
    return result


def _merge_unit(analysis: CppAnalysis, addition: CppAnalysis) -> None:
    """按 USR、位置和调用目标合并各 TU，保留跨 TU 调用证据。"""
    for usr, symbol in addition.symbols.items():
        existing = analysis.symbols.setdefault(usr, symbol)
        for field_name in ("declarations", "definitions"):
            values = getattr(existing, field_name)
            for location in getattr(symbol, field_name):
                if location not in values:
                    values.append(location)
    for path, item in addition.files.items():
        existing = analysis.files.setdefault(path, item)
        for field_name in ("includes", "functions", "types", "namespaces"):
            values = getattr(existing, field_name)
            for value in getattr(item, field_name):
                if value not in values:
                    values.append(value)
    for field_name in ("entry_points", "dependencies"):
        values = getattr(analysis, field_name)
        for value in getattr(addition, field_name):
            if value not in values:
                values.append(value)
    calls = {
        (call.caller_usr, call.callee_usr, call.location): call
        for call in analysis.calls
    }
    for call in addition.calls:
        key = (call.caller_usr, call.callee_usr, call.location)
        if key not in calls:
            analysis.calls.append(call)
            calls[key] = call
        else:
            for path in call.translation_units:
                if path not in calls[key].translation_units:
                    calls[key].translation_units.append(path)


def analyze_semantics(context: AnalysisContext, state: AnalysisState) -> AnalysisResult:
    """独立记录后端执行失败与 TU 诊断造成的部分语义覆盖。"""
    analysis = CppAnalysis(
        backend="libclang", analysis_level="semantic", semantic_status="failed"
    )
    state.artifacts.cpp = analysis
    allowed = {
        file.path.resolve()
        for file in state.artifacts.files
        if file.language in {Language.CPP, Language.CPP_HEADER}
    }
    coverage = analysis.coverage
    coverage.total_files = len(allowed)
    coverage.uncovered_files = sorted(allowed)
    try:
        database = find_compilation_database(
            context.repository.root, context.options.cpp_compile_commands
        )
        analysis.compile_commands = database
        analysis.translation_units = read_compilation_database(database)
        coverage.total_translation_units = len(analysis.translation_units)
        cindex, index, analysis.library_version = load_libclang()
    except Exception as exc:  # noqa: BLE001 - 将第三方初始化异常保留为后端失败原因。
        analysis.semantic_reason = str(exc)
        return AnalysisResult(AnalyzerName.CPP, errors=[str(exc)])
    warnings: list[str] = []
    parsed = 0
    for unit in analysis.translation_units:
        context.cancellation.raise_if_cancelled()
        if unit.status == "failed":
            coverage.failed_translation_units += 1
            analysis.diagnostics.append(
                CppDiagnostic("error", unit.reason or "编译条目不可用", unit.path)
            )
            continue
        if unit.path not in allowed:
            unit.status = "skipped"
            unit.reason = (
                "源文件不在扫描范围内，可能被排除、超出大小限制或不是 C++ 文件"
            )
            continue
        try:
            translation_unit = index.parse(str(unit.path), args=list(unit.arguments))
            parsed += 1
            has_errors = False
            for diagnostic in translation_unit.diagnostics:
                location = diagnostic.location
                severity = {
                    0: "ignored",
                    1: "note",
                    2: "warning",
                    3: "error",
                    4: "fatal",
                }.get(diagnostic.severity, "unknown")
                analysis.diagnostics.append(
                    CppDiagnostic(
                        severity,
                        diagnostic.spelling,
                        unit.path,
                        Path(location.file.name).resolve() if location.file else None,
                        location.line,
                        location.column,
                    )
                )
                has_errors |= diagnostic.severity >= cindex.Diagnostic.Error
            if has_errors:
                unit.status = "partial"
                unit.reason = "Clang 返回错误诊断；不采纳该 TU 的符号及直接调用"
                continue
            addition = _extract_unit(context, unit, translation_unit, allowed)
            _merge_unit(analysis, addition)
            unit.status = "completed"
        except AnalysisCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 隔离单个 TU 的异常并保留诊断，继续分析其余 TU。
            unit.status = "failed"
            unit.reason = f"无法解析翻译单元：{exc}"
            coverage.failed_translation_units += 1
            analysis.diagnostics.append(CppDiagnostic("error", unit.reason, unit.path))
    coverage.parsed_translation_units = parsed
    coverage.covered_files = len(analysis.files)
    coverage.uncovered_files = sorted(allowed - analysis.files.keys())
    for item in analysis.files.values():
        analysis.include_counts.update(item.includes)
    if not parsed:
        analysis.semantic_reason = (
            "没有可解析的翻译单元；请检查编译数据库条目和扫描范围"
        )
        return AnalysisResult(AnalyzerName.CPP, errors=[analysis.semantic_reason])
    incomplete = any(unit.status != "completed" for unit in analysis.translation_units)
    if incomplete or coverage.uncovered_files:
        analysis.semantic_status = "partial"
        analysis.semantic_reason = (
            f"完成 {sum(unit.status == 'completed' for unit in analysis.translation_units)}/"
            f"{coverage.total_translation_units} 个 TU；"
            f"覆盖 {coverage.covered_files}/{coverage.total_files} 个扫描文件"
        )
        warnings.append(analysis.semantic_reason)
    else:
        analysis.semantic_status = "completed"
    return AnalysisResult(AnalyzerName.CPP, warnings=warnings)
