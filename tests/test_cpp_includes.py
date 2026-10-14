"""验证不依赖编译环境的 C++ include 与条件提取。"""

from pathlib import Path

import pytest

from repopath.analyzer.cpp.includes import IncludeResolver, scan_source
from repopath.model.cpp import CppInclude


def test_scan_ignores_comments_strings_and_raw_strings() -> None:
    """字面量和注释中的伪指令不能成为依赖或函数。"""
    source = '''// #include "line.hpp"
/* #include <block.hpp>
int fake_comment() {} */
const char* ordinary = "#include <string.hpp>";
const char* raw = u8R"tag(
#include "raw.hpp"
int fake_raw() {}
)tag";
#include /* a comment */ "real.hpp" // tail
int real() { return 1'000; }
'''

    scanned = scan_source(source)

    assert [(item.name, item.line, item.kind) for item in scanned.includes] == [
        ("real.hpp", 9, "quoted"),
    ]
    assert "fake_comment" not in scanned.code
    assert "fake_raw" not in scanned.code
    assert "#include" not in scanned.code
    assert "int real() { return 1'000; }" in scanned.code
    assert len(scanned.code) == len(source)
    assert scanned.location(scanned.code.index("real()")) == (10, ())


def test_nested_conditions_preserve_elif_else_and_macros() -> None:
    """保留所有分支及其否定条件，宏 include 不伪装成文件名。"""
    scanned = scan_source('''#ifdef _WIN32
#include "windows.hpp"
#if FEATURE
int enabled() {}
#elif OTHER
#include SELECT_HEADER(OTHER)
#else
int fallback() {}
#endif
#else
#include <posix.hpp>
#endif
#ifndef OMIT_ENTRY
int main() {}
#endif
''')

    assert scanned.includes[0].conditions == ("defined(_WIN32)",)
    macro = scanned.includes[1]
    assert (macro.name, macro.kind, macro.resolution) == (
        "SELECT_HEADER(OTHER)", "macro", "macro",
    )
    assert macro.conditions == ("defined(_WIN32)", "!(FEATURE) && (OTHER)")
    assert scanned.includes[2].conditions == ("!(defined(_WIN32))",)
    assert scanned.location(scanned.code.index("enabled()")) == (
        4, ("defined(_WIN32)", "FEATURE"),
    )
    assert scanned.location(scanned.code.index("fallback()")) == (
        8, ("defined(_WIN32)", "!(FEATURE) && !(OTHER)"),
    )
    assert scanned.location(scanned.code.index("main()")) == (14, ("!defined(OMIT_ENTRY)",))


def test_continuations_keep_physical_locations_and_comment_rules() -> None:
    """指令、标识符与行注释的续行均按逻辑行识别，结果仍指向物理行。"""
    source = (
        '#if FLAG && \\\r\n    EXTRA\r\n'
        '#inc\\\r\nlude "long/\\\r\nname.hpp"\r\n'
        '// hidden \\\r\n#include "hidden.hpp"\r\n'
        'int ma\\\r\nin() {}\r\n'
        '#endif\r\n'
        'int after() {}\r\n'
    )

    scanned = scan_source(source)

    assert len(scanned.includes) == 1
    include = scanned.includes[0]
    assert (include.name, include.line) == ("long/name.hpp", 3)
    assert include.conditions == ("FLAG &&     EXTRA",)
    assert scanned.location(scanned.code.index("main()")) == (8, include.conditions)
    assert scanned.location(scanned.code.index("in()")) == (9, include.conditions)
    assert scanned.location(scanned.code.index("after()")) == (11, ())


def test_preprocessor_definitions_do_not_create_functions() -> None:
    """函数式宏和续行宏体不进入普通函数正则的输入。"""
    scanned = scan_source(
        '#define HELPER(x) int fake(x) { \\\nreturn x; }\n'
        "const char value = '\\'';\n"
        '#include HEADER\n'
        'int real() {}\n'
    )

    assert "fake" not in scanned.code
    assert "return x" not in scanned.code
    assert scanned.includes[0].kind == "macro"
    assert scanned.location(scanned.code.index("real()")) == (5, ())


def test_raw_string_does_not_splice_a_false_ending() -> None:
    """raw string 内的续行不能拼出假结束符并泄漏后续伪指令。"""
    source = (
        'const char* s = R"(raw )\\\n"\n'
        '#include "fake.hpp"\n'
        ')";\n'
        '#include "real.hpp"\n'
    )

    scanned = scan_source(source)

    assert [(item.name, item.line) for item in scanned.includes] == [("real.hpp", 5)]
    assert len(scanned.code) == len(source)
    assert "fake" not in scanned.code


def test_raw_looking_comment_and_real_raw_string_handle_continuations() -> None:
    """注释中的伪 raw string 不改变拼接规则，真实 raw 的所有内部续行均保留。"""
    source = (
        '// R"(fake \\\n#include "comment.hpp"\n'
        'const char* value = R"tag(\\\ntext )ta\\\ng"\n'
        '#include "inside.hpp"\n'
        ')tag";\n'
        '#include \\\n"outside.hpp"\n'
        'int after() {}\n'
    )

    scanned = scan_source(source)

    assert [item.name for item in scanned.includes] == ["outside.hpp"]
    assert scanned.includes[0].line == 8
    assert scanned.location(scanned.code.index("after()")) == (10, ())


def test_elifdef_and_elifndef_preserve_branch_conditions() -> None:
    """C++23 条件指令等价于对应的 defined 表达式，不继承前一分支。"""
    scanned = scan_source('''#if FIRST
#include "first.hpp"
#elifdef SECOND
#include "second.hpp"
#elifndef THIRD
#include "third.hpp"
#else
#include "last.hpp"
#endif
''')

    assert [include.conditions for include in scanned.includes] == [
        ("FIRST",),
        ("!(FIRST) && (defined(SECOND))",),
        ("!(FIRST) && !(defined(SECOND)) && (!defined(THIRD))",),
        ("!(FIRST) && !(defined(SECOND)) && !(!defined(THIRD))",),
    ]


def test_numeric_separators_do_not_hide_adjacent_character_literals() -> None:
    """保留现代数值字面量，同时屏蔽不带空格的字符字面量。"""
    scanned = scan_source("int a = 0xCA'FE; int b = 1'000; char c() { return'\\''; }\n")

    assert "0xCA'FE" in scanned.code
    assert "1'000" in scanned.code
    assert "return'" not in scanned.code


def test_filecrypt_names_keep_complete_include_suffix(tmp_path: Path) -> None:
    """FileCrypt 的两个 operations.hpp 不能因同名而串到错误模块。"""
    public = tmp_path / "include/filecrypt/app/operations.hpp"
    private = tmp_path / "src/app/operations.hpp"
    resolver = IncludeResolver(tmp_path, [public, private])
    exact = CppInclude("filecrypt/app/operations.hpp", 1, "angled")
    short = CppInclude("app/operations.hpp", 2, "angled")

    resolver.resolve(tmp_path / "src/cli/main.cpp", exact)
    resolver.resolve(tmp_path / "src/cli/main.cpp", short)

    assert (exact.resolution, exact.target) == ("suffix", public)
    assert short.resolution == "ambiguous"
    assert short.target is None
    assert short.candidates == [public, private]


def test_quoted_paths_prefer_current_directory_then_repository(tmp_path: Path) -> None:
    """同名文件优先当前文件目录；仓库根路径优先后缀猜测。"""
    local = tmp_path / "src/options.hpp"
    top = tmp_path / "options.hpp"
    other = tmp_path / "include/options.hpp"
    resolver = IncludeResolver(tmp_path, [local, top, other])
    quoted = CppInclude("options.hpp", 1, "quoted")
    angled = CppInclude("options.hpp", 2, "angled")

    resolver.resolve(tmp_path / "src/main.cpp", quoted)
    resolver.resolve(tmp_path / "src/main.cpp", angled)

    assert (quoted.resolution, quoted.target) == ("relative", local)
    assert (angled.resolution, angled.target) == ("repository", top)


@pytest.mark.parametrize("name", ["missing/options.hpp", "Options.hpp", "../../../options.hpp"])
def test_unmatched_paths_do_not_fall_back_to_basename(tmp_path: Path, name: str) -> None:
    """目录前缀、大小写和越根路径不可通过裸文件名兜底。"""
    resolver = IncludeResolver(tmp_path, [tmp_path / "include/options.hpp"])
    include = CppInclude(name, 1, "quoted")

    resolver.resolve(tmp_path / "src/main.cpp", include)

    assert include.resolution == "unresolved"
    assert include.target is None
    assert include.candidates == []


def test_relative_parent_paths_normalize_without_reading_extra_files(tmp_path: Path) -> None:
    """解析只使用扫描结果；磁盘中被排除的头文件不能形成依赖。"""
    header = tmp_path / "include/api.hpp"
    excluded = tmp_path / "src/excluded.hpp"
    excluded.parent.mkdir()
    excluded.touch()
    resolver = IncludeResolver(tmp_path, [header])
    relative = CppInclude("../include/./api.hpp", 1, "quoted")
    missing = CppInclude("excluded.hpp", 2, "quoted")

    resolver.resolve(tmp_path / "src/main.cpp", relative)
    resolver.resolve(tmp_path / "src/main.cpp", missing)

    assert (relative.resolution, relative.target) == ("relative", header)
    assert missing.resolution == "unresolved"


def test_macro_resolution_is_reset_without_guessing(tmp_path: Path) -> None:
    """即使宏文本恰巧等于仓库文件名，也不能推断宏展开结果。"""
    header = tmp_path / "CONFIG"
    resolver = IncludeResolver(tmp_path, [header])
    include = CppInclude("CONFIG", 1, "macro", target=header, candidates=[header])

    resolver.resolve(tmp_path / "main.cpp", include)

    assert include.resolution == "macro"
    assert include.target is None
    assert include.candidates == []
