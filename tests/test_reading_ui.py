"""阅读指南两端一致性、状态与来源展示测试。"""

import json
from pathlib import Path
from time import monotonic, sleep

import pytest
from streamlit.testing.v1 import AppTest

from repopath.analyzer.dependency_analyzer import DependencyAnalyzer
from repopath.core.service import analyze_repository
from repopath.interface import cli
from repopath.model.options import AnalysisOptions
from repopath.model.reading import (
    ReadingEvidence,
    ReadingGap,
    ReadingGuide,
    ReadingLocation,
    ReadingStep,
)
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository, RepositorySource
from repopath.model.result import AnalysisResult, AnalyzerName, AnalyzerStatus
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


def _render_report(report: "RepositoryReport") -> None:
    """通过真实 Streamlit 组件渲染已保存的报告。"""
    import streamlit as st

    from repopath.interface.ui.views import render_report

    render_report(report, st)


def _view(app: AppTest, label: str = "阅读指南（试验）") -> AppTest:
    """切换报告视图并检查页面没有异常。"""
    assert not app.exception
    next(
        item for item in app.segmented_control if item.label == "报告视图"
    ).set_value(label).run(timeout=10)
    assert not app.exception
    return app


def _wait_for_report(app: AppTest) -> RepositoryReport:
    """等待实际后台分析完成并返回 UI 使用的同一报告对象。"""
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if any(item.label == "报告视图" for item in app.segmented_control):
            report = app.session_state["repopath.analysis_runtime"].snapshot().report
            assert isinstance(report, RepositoryReport)
            return report
        sleep(0.05)
        app.run(timeout=10)
        assert not app.exception
    pytest.fail("Streamlit 后台分析未能在测试时限内完成")


@pytest.mark.parametrize("profile", ["fast", "standard"])
@pytest.mark.parametrize(
    ("files", "language_evidence"),
    [
        ({
            "README.md": "# Vector algebra\n\nUse the [public API](algebra.py).\n",
            "algebra.py": 'def combine(left, right):\n    """Combine two vectors."""\n    return left + right\n',
        }, "python_docstring"),
        ({
            "README.md": "# Message schema\n\n## Usage\n\nRead [the schema](messages.proto).\n",
            "messages.proto": 'syntax = "proto3";\nmessage Parcel { string id = 1; }\n',
        }, None),
        ({
            "README.md": "# Text codec\n\nUse [the interface](codec.hpp).\n",
            "codec.hpp": "// Decode one value.\nint decode(int value);\n",
            "codec.cpp": '#include "codec.hpp"\nint decode(int value) { return value + 1; }\n',
        }, "cpp_symbol"),
    ],
    ids=["python-library", "unknown-language-schema", "cpp-library"],
)
def test_ui_and_cli_share_reading_guide_for_different_repositories(
    tmp_path: Path, files: dict[str, str], language_evidence: str | None,
    profile: str,
) -> None:
    """从真实 UI 开关到 CLI JSON 核对指南，避免仅熟悉项目可用。"""
    repository = tmp_path / "repository"
    repository.mkdir()
    for name, content in files.items():
        (repository / name).write_text(content, encoding="utf-8")
    (repository / ".repopath.toml").write_text(
        f'[scan]\nprofile = "{profile}"\n', encoding="utf-8"
    )
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=10)
    app.text_input[0].set_value(str(repository)).run(timeout=10)
    next(
        item for item in app.checkbox if item.label == "试验性阅读指南"
    ).check()
    next(item for item in app.button if item.label == "分析仓库").click()
    app.run(timeout=20)
    report = _wait_for_report(app)
    assert report.options.reading_enabled
    assert report.reading_guide.steps
    _view(app)
    assert app.code
    assert any("1. " in item.value for item in app.text)
    assert any("证据状态：" in item.value for item in app.text)
    notes = next(item for item in app.expander if item.label == "分析说明")
    details = [item for item in app.expander if item.label.startswith("依据与片段")]
    assert not notes.proto.expanded
    assert details and all(not item.proto.expanded for item in details)
    assert any("本次能力范围" == item.value for item in notes.caption)
    assert {id(item) for item in app.code} == {
        id(code) for detail in details for code in detail.code
    }, "源码片段只出现在默认折叠的详情中"
    if profile == "standard" and language_evidence is not None:
        language_steps = [
            step for step in report.reading_guide.steps
            if step.kind in {"definition", "interface", "usage"}
            and any(evidence.kind == language_evidence for evidence in step.evidence)
        ]
        assert language_steps, "标准模式必须验证实际语言片段，而非仅文档导航"
        assert all(step.location.excerpt for step in language_steps)
        assert any(
            step.location.excerpt.strip() in [item.value for item in app.code]
            for step in language_steps
        )
        if language_evidence == "cpp_symbol":
            assert all(step.confidence == "candidate" for step in language_steps)
            assert any("接口声明" in item.value for item in app.text)
    if profile == "fast":
        assert not report.options.python_enabled
        assert not report.options.cpp_enabled
        assert not any(
            evidence.kind.startswith(("python_", "cpp_"))
            for step in report.reading_guide.steps for evidence in step.evidence
        )

    output = tmp_path / "cli-report.json"
    assert cli.main(
        [str(repository), "--reading-guide", "-o", str(output)]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    ui_payload = json.loads(JsonRenderer().render(report))
    assert payload["reading_guide"] == ui_payload["reading_guide"]
    _view(app, "报告")
    assert len(app.get("download_button")) == 2
    next(item for item in app.checkbox if item.label == "显示原始 JSON").check().run()
    preview = json.loads(app.code[0].value)
    assert preview["reading_guide"] == payload["reading_guide"]


def test_ui_reading_guide_survives_dependency_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """依赖图失败时指南仍展示文档证据，避免重复旧的依赖约束。"""
    (tmp_path / "README.md").write_text(
        "# Packet tools\n\n## Usage\n\nProcess a packet.\n", encoding="utf-8"
    )

    def fail(*args: object) -> None:
        raise RuntimeError("dependency graph unavailable")

    monkeypatch.setattr(DependencyAnalyzer, "analyze", fail)
    report = analyze_repository(
        tmp_path, options=AnalysisOptions(reading_enabled=True, git_enabled=False)
    )
    assert report.analyzer_result(AnalyzerName.DEPENDENCIES).status == AnalyzerStatus.FAILED
    assert report.analyzer_result(AnalyzerName.READING).successful
    app = AppTest.from_function(_render_report, args=(report,)).run()
    _view(app)
    assert app.code
    assert any("README.md:" in item.value for item in app.text)


@pytest.mark.parametrize(
    ("status", "expected", "element"),
    [
        (AnalyzerStatus.NOT_RUN, "not_run", "info"),
        (AnalyzerStatus.FAILED, "failed", "error"),
        (AnalyzerStatus.COMPLETED, "证据不足", "info"),
    ],
)
def test_ui_reading_distinguishes_unavailable_and_empty_results(
    tmp_path: Path, status: AnalyzerStatus, expected: str, element: str
) -> None:
    """执行记录决定未运行和失败；完成后的空指南明确说明证据不足。"""
    report = RepositoryReport(
        Repository.from_path(tmp_path),
        analyzer_results={
            AnalyzerName.READING: AnalysisResult(
                AnalyzerName.READING, status=status, reason="test state"
            )
        },
    )
    app = AppTest.from_function(_render_report, args=(report,)).run()
    _view(app)
    assert any(expected in item.value for item in app.get(element))
    assert not app.code


@pytest.mark.parametrize("failed", [False, True], ids=["partial", "failed-partial"])
def test_ui_reading_retains_evidence_after_remote_files_are_gone(
    tmp_path: Path, failed: bool,
) -> None:
    """只用模型中的片段展示主题、范围、证据、关联、缺口和预算信息。"""
    location = ReadingLocation("docs/usage.md", 3, 8, "Choose a format.\n")
    alternate = ReadingLocation("docs/usage.md", 3, 8, "Another preserved excerpt.\n")
    related = ReadingLocation("src/codec.py", 20, 24, "def decode(value):\n    return value\n")
    steps = [
        ReadingStep(
            str(index), "使用说明", "usage", f"如何使用 {index}？", "文档提供使用示例。",
            location, confidence=confidence,
            evidence=(
                ReadingEvidence("local_link", location, "文档指向源码片段。"),
                ReadingEvidence("document_section", alternate, "同一位置的另一段预览。"),
            ),
            related=(related,),
        )
        for index, confidence in enumerate(("observed", "documented", "candidate"))
    ]
    report = RepositoryReport(
        Repository.from_path(tmp_path),
        source=RepositorySource.github("example/codec", "fixed-revision"),
        options=AnalysisOptions(reading_enabled=True, reading_limit=1),
        reading_guide=ReadingGuide(
            steps=steps,
            gaps=[ReadingGap("ambiguous", "同名声明不能确定关联。", "src/codec.py")],
            capabilities=["Markdown 文档与本地链接"],
            candidate_count=7, scanned_files=12, truncated=True,
        ),
        analyzer_results={
            AnalyzerName.READING: AnalysisResult(
                AnalyzerName.READING,
                status=AnalyzerStatus.FAILED if failed else AnalyzerStatus.COMPLETED,
                errors=["one source could not be read"] if failed else [],
            )
        },
    )
    app = AppTest.from_function(_render_report, args=(report,)).run()
    _view(app)
    assert any("部分" in item.value for item in app.warning)
    if failed:
        assert any("failed" in item.value for item in app.error)
        assert any("one source could not be read" in item.value for item in app.error)
    assert any("内容已截断" in item.value and "缺口 1 项" in item.value for item in app.warning)
    notes = next(item for item in app.expander if item.label == "分析说明")
    detail = next(item for item in app.expander if item.label.startswith("依据与片段"))
    assert not notes.proto.expanded and not detail.proto.expanded
    assert not notes.warning and not notes.error
    assert not detail.warning and not detail.error
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["候选片段"] == "7"
    assert metrics["扫描文件"] == "12"
    assert any("docs/usage.md:3-8" in item.value for item in app.text)
    assert any("src/codec.py:20-24" in item.value for item in app.text)
    assert any("文档指向源码片段" in item.value for item in app.text)
    assert location.excerpt.rstrip() in [item.value for item in app.code]
    assert [item.value for item in app.code].count(location.excerpt.rstrip()) == 1
    assert alternate.excerpt.rstrip() in [item.value for item in detail.code]
    assert related.excerpt.rstrip() in [item.value for item in app.code]
    assert len(app.code) == len(detail.code) == 3
    assert any("同名声明不能确定关联" in item.value for item in app.text)
    assert any("同名声明不能确定关联" in item.value for item in notes.text)
    assert any("另一段预览" in item.value for item in detail.text)
    assert any("observed" in item.value for item in app.text)
    assert sum(item.label.startswith("依据与片段") for item in app.expander) == 1
    for page, state in ((2, "documented"), (3, "candidate")):
        next(item for item in app.number_input if item.label == "阅读指南页码").set_value(page).run()
        assert not app.exception
        assert any(state in item.value for item in app.text)


def test_ui_markdown_download_defaults_to_summary_and_keeps_full_option(tmp_path: Path) -> None:
    """下载和预览共用 CLI 的详情选项，摘要隐藏片段但完整报告仍可核对。"""
    (tmp_path / "guide.md").write_text("# Input format\n\nChoose a format.\n", encoding="utf-8")
    report = analyze_repository(
        tmp_path, options=AnalysisOptions(reading_enabled=True, git_enabled=False)
    )
    app = AppTest.from_function(_render_report, args=(report,)).run()
    _view(app, "报告")
    detail = next(item for item in app.selectbox if item.label == "Markdown 详情")
    assert detail.value == "摘要"
    assert len(app.get("download_button")) == 2
    next(item for item in app.checkbox if item.label == "显示 Markdown 预览").check().run()
    assert app.code[0].value == MarkdownRenderer().render(report, detail="summary").strip()
    assert "Choose a format." not in app.code[0].value
    detail = next(item for item in app.selectbox if item.label == "Markdown 详情")
    detail.select("完整").run()
    assert not app.exception
    assert app.code[0].value == MarkdownRenderer().render(report, detail="full").strip()
    assert "Choose a format." in app.code[0].value


def test_ui_cpp_shows_include_candidates_and_conditional_entries(tmp_path: Path) -> None:
    """C++ 页面与 CLI 同样可查看匹配目标、歧义和各条件入口。"""
    (tmp_path / "main.cpp").write_text(
        '#ifdef _WIN32\n#include "shared.hpp"\nint wmain() { return 0; }\n'
        '#else\n#include HEADER_MACRO\nint main() { return 0; }\n#endif\n',
        encoding="utf-8",
    )
    for directory in ("first", "second"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "shared.hpp").write_text("// header\n", encoding="utf-8")
    report = analyze_repository(tmp_path, options=AnalysisOptions(git_enabled=False))
    app = AppTest.from_function(_render_report, args=(report,)).run()
    _view(app, "C++")
    includes = next(item.value for item in app.dataframe if "候选目标" in item.value.columns)
    assert set(includes["匹配"]) == {"ambiguous", "macro"}
    ambiguous = includes[includes["匹配"] == "ambiguous"].iloc[0]
    assert "first/shared.hpp" in ambiguous["候选目标"]
    assert "second/shared.hpp" in ambiguous["候选目标"]
    assert "_WIN32" in ambiguous["条件"]
    entries = next(item.value for item in app.dataframe if "名称" in item.value.columns and "条件" in item.value.columns)
    assert set(entries["名称"]) == {"main", "wmain"}
    assert len(set(entries["条件"])) == 2
    assert any("条件不求值" in item.value for item in app.caption)
