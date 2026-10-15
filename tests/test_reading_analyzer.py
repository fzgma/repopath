"""用不同仓库形态及一致变形验证导读证据，不固定某个项目的阅读主线。"""

from dataclasses import asdict
from pathlib import Path

import pytest

from repopath.analyzer import reading_support
from repopath.analyzer.reading_analyzer import ReadingAnalyzer
from repopath.core.context import AnalysisContext
from repopath.core.control import AnalysisCancelled
from repopath.core.service import analyze_repository
from repopath.model.file import FileRecord
from repopath.model.language import detect_language
from repopath.model.options import AnalysisOptions
from repopath.model.repository import Repository, RepositorySource
from repopath.model.result import AnalysisState, AnalyzerName
from repopath.provider.filesystem import FileSystemProvider
from repopath.provider.git import UnavailableGitProvider


def _write(root: Path, files: dict[str, str]) -> None:
    """创建没有固定目录约定的临时仓库。"""
    for path, source in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


def _guide(
    root: Path, *, python: bool = True, cpp: bool = True, limit: int = 40
):
    """通过真实服务生成指南，但禁用与新机制无关的图和 Git。"""
    report = analyze_repository(
        root,
        options=AnalysisOptions(
            reading_enabled=True,
            reading_limit=limit,
            python_enabled=python,
            cpp_enabled=cpp,
            dependencies_enabled=False,
            insights_enabled=False,
            git_enabled=False,
        ),
    )
    assert report.analyzer_result(AnalyzerName.READING).successful
    assert (
        report.analyzer_result(AnalyzerName.DEPENDENCIES).status == "not_run"
    )
    return report.reading_guide


def _context(root: Path) -> tuple[AnalysisContext, AnalysisState]:
    """直接构造导读阶段，便于验证读取与取消边界。"""
    repository = Repository.from_path(root)
    context = AnalysisContext(
        repository=repository,
        source=RepositorySource.local(root),
        filesystem=FileSystemProvider(repository),
        git=UnavailableGitProvider("test"),
        options=AnalysisOptions.for_profile("fast").with_overrides(
            reading_enabled=True
        ),
    )
    state = AnalysisState()
    state.artifacts.files = [
        FileRecord(path, detect_language(path), 1, 1)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return context, state


def test_library_without_main_has_export_definition_and_usage(
    tmp_path: Path,
) -> None:
    """库只凭显式导出和静态使用也能形成可定位步骤，不要求 main。"""
    _write(
        tmp_path,
        {
            "strange/curve.py": '__all__ = ["bend"]\n\ndef bend(value):\n    return value + 1\n',
            "strange/__init__.py": "",
            "demonstration.py": "from strange.curve import bend as adjust\nresult = adjust(3)\n",
        },
    )
    guide = _guide(tmp_path)
    assert {step.kind for step in guide.steps} >= {
        "interface",
        "definition",
        "usage",
    }
    usage = next(step for step in guide.steps if step.kind == "usage")
    assert usage.location.path == "demonstration.py"
    assert usage.location.line == 2
    assert usage.confidence == "candidate"
    assert usage.related[0].path == "strange/curve.py"
    assert usage.related[0].line == 3


def test_unknown_language_is_navigable_from_non_readme_document(
    tmp_path: Path,
) -> None:
    """陌生语言和无 README 的仓库仍有显式文档导航，不假造符号能力。"""
    _write(
        tmp_path,
        {
            "notes/orientation.md": "# Contract\n[Schema](../shapes/data.custom#L2-L3)\n",
            "shapes/data.custom": "schema x\nfield left\nfield right\n",
        },
    )
    guide = _guide(tmp_path, python=False, cpp=False)
    step = next(
        item for item in guide.steps if item.location.path.endswith(".custom")
    )
    assert step.kind == "document"
    assert (step.location.line, step.location.end_line) == (2, 3)
    assert "field left" in step.location.excerpt
    assert step.evidence[0].location.path == "notes/orientation.md"
    assert all(
        item.kind not in {"definition", "usage"} for item in guide.steps
    )


def test_manifest_supports_subprojects_and_ambiguous_python_paths(
    tmp_path: Path,
) -> None:
    """子项目清单分别提供来源，重复模块路径保留歧义而不猜布局。"""
    _write(
        tmp_path,
        {
            "north/pyproject.toml": '[project.scripts]\nlaunch = "orbit:go"\n',
            "north/one/orbit.py": "def go():\n    pass\n",
            "north/two/orbit.py": "def go():\n    pass\n",
            "south/package.json": '{"exports": {".": "./a.rs", "./b": "./b.rs"}}',
            "south/a.rs": "pub fn a() {}\n",
            "south/b.rs": "pub fn b() {}\n",
        },
    )
    guide = _guide(tmp_path)
    assert any(gap.kind == "ambiguous_entry" for gap in guide.gaps)
    assert not any(step.kind == "definition" for step in guide.steps)
    interfaces = [step for step in guide.steps if step.kind == "interface"]
    assert {location.path for item in interfaces for location in item.related} == {
        "south/a.rs",
        "south/b.rs",
    }


def test_document_move_and_consistent_symbol_rename_preserve_evidence(
    tmp_path: Path,
) -> None:
    """目录和命名变化不会改变分析机制，只有对应位置和名称随之变化。"""
    first, second = tmp_path / "first", tmp_path / "second"
    _write(
        first,
        {
            "overview.md": "# Usage\n[Library](module.py)\n",
            "module.py": '__all__ = ["blend"]\ndef blend(x):\n    return x\n',
            "sample.py": "from module import blend\nblend(1)\n",
        },
    )
    _write(
        second,
        {
            "paper/route.md": "# Usage\n[Library](../renamed.py)\n",
            "renamed.py": '__all__ = ["merge"]\ndef merge(x):\n    return x\n',
            "use.py": "from renamed import merge\nmerge(1)\n",
        },
    )
    original, renamed = _guide(first), _guide(second)
    assert sorted(step.kind for step in original.steps) == sorted(
        step.kind for step in renamed.steps
    )
    assert sorted(step.confidence for step in original.steps) == sorted(
        step.confidence for step in renamed.steps
    )
    assert {step.location.path for step in renamed.steps} == {
        "paper/route.md",
        "renamed.py",
        "use.py",
    }


def test_repeated_links_and_undocumented_large_file_do_not_win(
    tmp_path: Path,
) -> None:
    """重复链接及无说明的大文件不能仅靠规模增加推荐机会。"""
    _write(
        tmp_path,
        {
            "map.md": "# Map\n[API](small.py)\n",
            "small.py": '__all__ = ["act"]\ndef act():\n    return 1\n',
        },
    )
    baseline = _guide(tmp_path)
    _write(
        tmp_path,
        {
            "map.md": "# Map\n" + "[API](small.py)\n" * 100,
            "noise.py": "\n".join(
                f"def item_{number}():\n    return 1\n"
                for number in range(1000)
            ),
        },
    )
    changed = _guide(tmp_path)
    assert changed.candidate_count == baseline.candidate_count
    assert all(step.location.path != "noise.py" for step in changed.steps)


def test_shadowed_import_and_duplicate_definitions_are_not_bound(
    tmp_path: Path,
) -> None:
    """已知重绑定和同名重复定义不会得到肯定的使用关联。"""
    _write(
        tmp_path,
        {
            "ambiguous.py": '__all__ = ["work"]\ndef work():\n    pass\ndef work():\n    pass\n',
            "clear.py": '__all__ = ["draw"]\ndef draw():\n    pass\n',
            "consumer.py": "from ambiguous import work\nfrom clear import draw\nwork()\ndef wrapper(draw):\n    return draw()\n",
        },
    )
    guide = _guide(tmp_path)
    assert not any(step.kind == "usage" for step in guide.steps)
    assert any(gap.kind == "unresolved_export" for gap in guide.gaps)


def test_broken_files_do_not_discard_good_document_or_module(
    tmp_path: Path,
) -> None:
    """局部语法和清单失败均可解释，并保留其他来源。"""
    _write(
        tmp_path,
        {
            "design.md": "# Design\nA description.\n",
            "broken.py": "def invalid(:\n",
            "package.json": "{invalid}",
            "clean.py": '__all__ = ["helper"]\ndef helper():\n    """A useful description."""\n    return 1\n',
        },
    )
    guide = _guide(tmp_path)
    assert {gap.kind for gap in guide.gaps} >= {
        "invalid_python",
        "invalid_manifest",
    }
    assert {step.location.path for step in guide.steps} >= {
        "design.md",
        "clean.py",
    }


def test_language_switches_disable_syntax_even_with_document_links(
    tmp_path: Path,
) -> None:
    """语言关闭后仍允许通用链接导航，但不能偷偷解析符号。"""
    _write(
        tmp_path,
        {
            "manual.md": "# Notes\n[Code](unit.py)\n[Header](unit.hpp)\n",
            "unit.py": 'def run():\n    """Describe."""\n    pass\n',
            "unit.hpp": "int run();\n",
        },
    )
    guide = _guide(tmp_path, python=False, cpp=False)
    assert guide.steps
    assert all(step.kind == "document" for step in guide.steps)
    assert {gap.kind for gap in guide.gaps} >= {
        "python_unavailable",
        "cpp_unavailable",
    }


def test_cpp_overloads_remain_candidates_with_include_evidence(
    tmp_path: Path,
) -> None:
    """无 main 的 C++ 库通过显式文档和 include 关联，重载不伪装绑定。"""
    _write(
        tmp_path,
        {
            "explain.md": "# Contract\n[Declarations](shape.hpp)\n",
            "shape.hpp": "int fold(int x);\nint fold(double x);\n",
            "impl.cc": '#include "shape.hpp"\nint fold(int x) { return x; }\nint fold(double x) { return 1; }\n',
        },
    )
    guide = _guide(tmp_path)
    definitions = [step for step in guide.steps if step.kind == "definition"]
    assert len(definitions) == 2
    assert all(step.confidence == "candidate" for step in definitions)
    assert all(len(step.related) == 2 for step in definitions)
    assert any(
        step.kind == "usage" and step.location.line == 1
        for step in guide.steps
    )
    assert any(gap.kind == "ambiguous_cpp_symbol" for gap in guide.gaps)


def test_external_links_and_unscanned_targets_are_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不跟随仓库外、绝对、远端或未扫描目标，输出不泄露绝对路径。"""
    root = tmp_path / "repository"
    _write(
        root,
        {
            "index.md": "# Index\n[out](../private.md)\n[net](https://example.invalid/a)\n[abs](/private.md)\n[missing](absent.py)\n",
        },
    )
    (tmp_path / "private.md").write_text("PRIVATE", encoding="utf-8")
    context, state = _context(root)
    seen: list[Path] = []
    original = context.filesystem.read_text

    def read(path: Path) -> str | None:
        seen.append(path)
        return original(path)

    monkeypatch.setattr(context.filesystem, "read_text", read)
    ReadingAnalyzer().analyze(context, state)
    guide = state.artifacts.reading_guide
    assert set(seen) == {root / "index.md"}
    assert {gap.kind for gap in guide.gaps} >= {
        "outside_link",
        "unresolved_link",
    }
    assert "PRIVATE" not in str(asdict(guide))
    assert str(tmp_path) not in str(asdict(guide))


def test_resolved_symlink_outside_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """即使文件列表包含链接，解析后的外部目标仍不能被读取。"""
    root = tmp_path / "repository"
    _write(
        root,
        {
            "index.md": "# Index\n[linked](linked.py)\n",
            "linked.py": "SECRET\n",
        },
    )
    context, state = _context(root)
    original = Path.resolve

    def resolve(path: Path, strict: bool = False) -> Path:
        if path == root / "linked.py":
            return tmp_path / "external.py"
        return original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    ReadingAnalyzer().analyze(context, state)
    guide = state.artifacts.reading_guide
    assert any(gap.kind == "outside_root" for gap in guide.gaps)
    assert "SECRET" not in str(asdict(guide))


def test_read_budget_keeps_other_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """大文件不被当作完整语法截断解析，其他文件仍可阅读。"""
    _write(
        tmp_path,
        {
            "large.md": "# Large\n" + "x" * 3000,
            "small.md": "# Small\nUseful.\n",
        },
    )
    monkeypatch.setattr(reading_support, "MAX_FILE_BYTES", 2000)
    guide = _guide(tmp_path)
    assert guide.truncated
    assert {step.location.path for step in guide.steps} == {"small.md"}
    assert any(gap.kind == "read_budget" for gap in guide.gaps)


def test_cancel_during_reading_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读取触发取消后下一证据边界立即退出，不产出假成功。"""
    _write(tmp_path, {"notes.md": "# One\nText.\n# Two\nText.\n"})
    context, state = _context(tmp_path)
    original = context.filesystem.read_text

    def read(path: Path) -> str | None:
        context.cancellation.cancel()
        return original(path)

    monkeypatch.setattr(context.filesystem, "read_text", read)
    with pytest.raises(AnalysisCancelled):
        ReadingAnalyzer().analyze(context, state)


def test_no_evidence_does_not_fill_steps_with_statistics(
    tmp_path: Path,
) -> None:
    """普通函数有无注释都不靠数量补满线索，空结果不虚报截断。"""
    _write(
        tmp_path,
        {
            "many.py": "\n".join(
                f"def unnamed_{index}():\n    pass\n" for index in range(50)
            ),
            "documented.py": "\n".join(
                f'def part_{index}():\n    """Describe part."""\n    pass\n'
                for index in range(100)
            ),
            "single.py": 'def single():\n    """Describe another component."""\n    pass\n',
        },
    )
    guide = _guide(tmp_path, limit=2)
    assert guide.steps == []
    assert guide.candidate_count == 0
    assert not guide.truncated
    assert any(gap.kind == "no_evidence" for gap in guide.gaps)


def test_markdown_fences_and_inline_code_do_not_create_anchors(
    tmp_path: Path,
) -> None:
    """长围栏中的短围栏、带文字的伪关闭及内联代码都不是导航证据。"""
    _write(
        tmp_path,
        {
            "notes.md": (
                "# Actual\n````markdown\n```\n[Fake](hidden.py)\n"
                "```` still code\n[Fake](hidden.py)\n````\n"
                "`[Fake](hidden.py)`\n    [Fake](hidden.py)\n"
            ),
            "hidden.py": "def unmentioned():\n    pass\n",
        },
    )
    guide = _guide(tmp_path)
    assert guide.steps
    assert all(step.location.path == "notes.md" for step in guide.steps)
    assert all(step.confidence == "documented" for step in guide.steps)


def test_stale_line_link_does_not_seed_unrelated_definitions(
    tmp_path: Path,
) -> None:
    """已知失效的行号不应退回整文件并扩展出伪阅读关联。"""
    _write(
        tmp_path,
        {
            "notes.md": "# Notes\n[Stale](code.py#L999)\n",
            "code.py": "def unrelated():\n    pass\n",
        },
    )
    guide = _guide(tmp_path)
    assert all(step.kind == "document" for step in guide.steps)
    assert all(step.location.path == "notes.md" for step in guide.steps)
    assert any(gap.kind == "unresolved_fragment" for gap in guide.gaps)


def test_explicit_line_anchor_only_seeds_overlapping_python_definition(
    tmp_path: Path,
) -> None:
    """明确行范围只支持该范围内的片段，不能扩展到文件里的全部函数。"""
    _write(
        tmp_path,
        {
            "notes.md": "# Notes\n[One](code.py#L3-L4)\n",
            "code.py": "def unrelated():\n    pass\ndef selected():\n    pass\n",
        },
    )
    guide = _guide(tmp_path)
    definitions = [step for step in guide.steps if step.kind == "definition"]
    assert len(definitions) == 1
    assert definitions[0].location.line == 3


def test_single_line_exports_preserve_distinct_names(tmp_path: Path) -> None:
    """同一行导出多个名字时不能用第一个摘要覆盖其余事实。"""
    _write(
        tmp_path,
        {
            "module.py": '__all__ = ["first", "second"]\ndef first():\n    pass\ndef second():\n    pass\n',
        },
    )
    guide = _guide(tmp_path)
    interfaces = [step for step in guide.steps if step.kind == "interface"]
    assert {
        (location.path, location.line)
        for step in interfaces
        for location in step.related
    } == {("module.py", 2), ("module.py", 4)}
    summaries = "\n".join(step.summary for step in interfaces)
    assert "first" in summaries and "second" in summaries


def test_relation_and_plan_limits_are_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关联分析触及预算要标记截断；选择少量建议不等于分析失败。"""
    _write(
        tmp_path,
        {
            "notes.md": "# Notes\n[Many](code.py)\n",
            "code.py": "\n".join(
                f"def function_{index}():\n    pass\n" for index in range(20)
            ),
        },
    )
    monkeypatch.setattr(reading_support, "MAX_FACTS", 3)
    guide = _guide(tmp_path, limit=2)
    assert guide.truncated
    assert 0 < len(guide.steps) <= 2
    assert guide.candidate_count > len(guide.steps)
    assert any(gap.kind == "relation_budget" for gap in guide.gaps)


def test_association_preview_limit_does_not_claim_complete_candidates(
    tmp_path: Path,
) -> None:
    """大量同名声明只显示少量关联时，要明确仍有未显示的候选。"""
    _write(
        tmp_path,
        {
            "module.py": '__all__ = ["same"]\n'
            + "def same():\n    pass\n" * 10,
        },
    )
    guide = _guide(tmp_path)
    interface = next(step for step in guide.steps if step.kind == "interface")
    related = {(location.path, location.line) for location in interface.related}
    expected = {("module.py", line) for line in range(2, 22, 2)}
    assert related
    assert related < expected
    assert guide.truncated
    assert any(gap.kind == "related_limit" for gap in guide.gaps)


def test_cross_topic_deduplication_does_not_report_truncation(
    tmp_path: Path,
) -> None:
    """文档和导出同时引用一处定义时，候选按最终身份计数而非主题数量。"""
    _write(
        tmp_path,
        {
            "notes.md": "# Notes\n[Code](module.py)\n",
            "module.py": '__all__ = ["work"]\ndef work():\n    pass\n',
        },
    )
    complete = _guide(tmp_path, limit=20)
    limited = _guide(tmp_path, limit=3)
    assert limited.candidate_count == complete.candidate_count
    for guide, limit in ((complete, 20), (limited, 3)):
        locations = [
            (step.kind, step.location.path, step.location.line)
            for step in guide.steps
        ]
        assert 0 < len(guide.steps) <= limit
        assert guide.candidate_count >= len(guide.steps)
        assert len(locations) == len(set(locations))
        assert not guide.truncated
        assert not any(gap.kind == "selection_limit" for gap in guide.gaps)
