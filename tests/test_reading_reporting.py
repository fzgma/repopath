"""阅读指南的机器字段、两种 Markdown 详情与显示边界测试。"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from repopath.model.insight import ReadingRecommendation
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
from repopath.renderer.reading import READING_BOUNDARY, format_location


@pytest.fixture
def reading_report(tmp_path: Path) -> RepositoryReport:
    """使用不存在于磁盘的片段，确保展示仅依赖共用报告模型。"""
    report = RepositoryReport(
        repository=Repository(tmp_path, display_name="sample"),
        source=RepositorySource.github("https://github.com/owner/sample", "abc123"),
        options=AnalysisOptions(reading_enabled=True, git_enabled=False),
        reading_guide=ReadingGuide(
            steps=[ReadingStep(
                id="docs:usage",
                topic="使用方式",
                kind="document",
                question="如何使用公开接口？",
                summary="文档给出一段接口使用示例。",
                location=ReadingLocation("docs/usage.md", 3, 12, "sample.open()"),
                confidence="documented",
                evidence=(ReadingEvidence(
                    "document_link",
                    ReadingLocation("README.md", 7, 7, "[usage](docs/usage.md)"),
                    "说明文档直接链接到此片段。",
                ),),
                related=(ReadingLocation("src/api.py", 8, 19, "def open():\n    pass"),),
            )],
            gaps=[ReadingGap("ambiguous", "同名接口有多个实现候选。", "src/api.py")],
            capabilities=["文档链接定位", "Python 声明与片段"],
            candidate_count=4,
            scanned_files=9,
        ),
        analyzer_results={
            AnalyzerName.READING: AnalysisResult(AnalyzerName.READING),
            AnalyzerName.INSIGHTS: AnalysisResult(AnalyzerName.INSIGHTS),
        },
    )
    report.insights.reading_order.append(ReadingRecommendation(
        rank=1, node_id="python:utility", path="utility.py", language="Python",
        reading_priority_score=42.0, entry_distance=None, reasons=("被引用次数较多",),
    ))
    return report


def _guide_section(markdown: str) -> str:
    """只提取新指南，避免旧统计章节影响语义断言。"""
    return markdown.split("## 阅读指南（实验）", 1)[1].split("\n## ", 1)[0]


def test_json_keeps_reading_evidence_and_existing_insights(
    reading_report: RepositoryReport,
) -> None:
    """新契约包含真实状态和所有证据，原有榜单不被重写。"""
    payload = json.loads(JsonRenderer().render(reading_report))
    guide = payload["reading_guide"]
    assert payload["schema_version"] == "0.7"
    assert payload["analysis"]["reading_enabled"] is True
    assert guide["experimental"] is True
    assert guide["enabled"] is True
    assert guide["status"] == "completed"
    assert guide["reason"] is None
    assert guide["warnings"] == []
    assert guide["errors"] == []
    assert guide["candidate_count"] == 4
    assert guide["scanned_files"] == 9
    assert guide["truncated"] is False
    step = guide["steps"][0]
    assert step["id"] == "docs:usage"
    assert step["question"] == "如何使用公开接口？"
    assert step["topic"] == "使用方式"
    assert step["confidence"] == "documented"
    assert step["location"] == {
        "path": "docs/usage.md", "line": 3, "end_line": 12,
        "excerpt": "sample.open()",
    }
    assert step["evidence"][0]["kind"] == "document_link"
    assert step["evidence"][0]["location"]["path"] == "README.md"
    assert step["related"][0]["end_line"] == 19
    assert guide["gaps"][0]["path"] == "src/api.py"
    assert guide["capabilities"] == ["文档链接定位", "Python 声明与片段"]
    assert payload["insights"]["reading_order"][0]["reading_priority_score"] == 42.0
    assert payload["insights"]["reading_order"][0]["reasons"] == ["被引用次数较多"]
    assert str(reading_report.repository.root) not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_markdown_preserves_reading_questions_locations_and_evidence(
    reading_report: RepositoryReport, detail: str,
) -> None:
    """摘要给出位置与事实状态，完整报告再提供原文和全部阅读依据。"""
    original = JsonRenderer().render(reading_report)
    markdown = MarkdownRenderer().render(reading_report, detail=detail)
    guide = _guide_section(markdown)
    for expected in (
        "文档给出一段接口使用示例。", "docs/usage.md:3-12",
        "文档摘录", "文档片段", "部分阅读线索", READING_BOUNDARY,
    ):
        assert expected in guide
    if detail == "full":
        for expected in (
            "使用方式", "如何使用公开接口？", "sample.open()", "README.md:7",
            "[usage](docs/usage.md)", "说明文档直接链接到此片段。",
            "src/api.py:8-19", "def open():\n    pass", "文档链接",
            "同名接口有多个实现候选。", "文档链接定位", "Python 声明与片段",
            "扫描 9 个文件，4 个候选。",
        ):
            assert expected in guide
    else:
        assert "--detail full" in guide
        assert "限制：" in guide
        assert "```" not in guide
        assert "sample.open()" not in guide
    assert "结构统计（旧排序）" in markdown
    assert "utility.py" in markdown
    assert str(reading_report.repository.root) not in markdown
    assert JsonRenderer().render(reading_report) == original


@pytest.mark.parametrize("status,reason,expected", [
    (AnalyzerStatus.NOT_RUN, "配置未启用", "阅读指南未运行"),
    (AnalyzerStatus.FAILED, "读取失败", "阅读指南分析失败"),
    (AnalyzerStatus.COMPLETED, None, "未找到可展示的阅读线索"),
])
def test_reading_availability_is_not_presented_as_understanding(
    reading_report: RepositoryReport,
    status: AnalyzerStatus, reason: str | None, expected: str,
) -> None:
    """未知、失败与无证据具有不同说明，空步骤不代表成功理解。"""
    reading_report.reading_guide = ReadingGuide()
    reading_report.analyzer_results[AnalyzerName.READING] = AnalysisResult(
        AnalyzerName.READING, status=status, reason=reason,
    )
    if status == AnalyzerStatus.NOT_RUN:
        reading_report.options = reading_report.options.with_overrides(reading_enabled=False)
    guide = _guide_section(MarkdownRenderer().render(reading_report, detail="summary"))
    assert expected in guide
    assert f"`{status}`" in guide
    if reason:
        assert reason in guide
    payload = json.loads(JsonRenderer().render(reading_report))["reading_guide"]
    assert payload["status"] == status
    assert payload["reason"] == reason
    assert payload["steps"] == []


def test_missing_execution_record_remains_unknown(
    reading_report: RepositoryReport,
) -> None:
    """开启选项与实际执行记录独立，不能凭开启状态推断完成。"""
    reading_report.analyzer_results.pop(AnalyzerName.READING)
    payload = json.loads(JsonRenderer().render(reading_report))["reading_guide"]
    assert payload["enabled"] is True
    assert payload["status"] == "not_run"
    assert payload["reason"] == "没有执行记录"
    guide = _guide_section(MarkdownRenderer().render(reading_report))
    assert "没有执行记录" in guide
    assert "线索 1" not in guide


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_analysis_and_display_truncation_are_distinct(
    reading_report: RepositoryReport, detail: str,
) -> None:
    """展示预算不丢失 JSON 证据，扫描预算不虚称 JSON 包含未分析内容。"""
    reading_report.options = reading_report.options.with_overrides(result_limit=1)
    step = reading_report.reading_guide.steps[0]
    reading_report.reading_guide.steps = [replace(
        step,
        evidence=step.evidence + (ReadingEvidence(
            "symbol", ReadingLocation("src/second.py", 22, 23, "second_evidence"),
            "另一处声明",
        ),),
        related=step.related + (ReadingLocation("src/second.py", 30, 32, "second_related"),),
    ), replace(step, id="docs:second", question="另一个阅读问题")]
    reading_report.reading_guide.gaps.append(ReadingGap("unsupported", "未分析其他语言调用"))
    reading_report.reading_guide.truncated = True
    guide = _guide_section(MarkdownRenderer().render(reading_report, detail=detail))
    assert "已截断" in guide
    if detail == "full":
        assert "线索 2：另一个阅读问题" in guide
        assert "其余 1 条证据在此省略" in guide
        assert "其余 1 条关联位置在此省略" in guide
        assert "其余 1 条缺口在此省略" in guide
        assert "不包含未入选候选、超预算关联或未分析内容" in guide
    else:
        assert guide.count("| docs/usage.md:3-12 |") == 2
        assert "其余 1 条限制类别在此省略" in guide
        assert "--detail full" in guide
    assert "second_evidence" not in guide
    assert "second_related" not in guide
    payload = json.loads(JsonRenderer().render(reading_report))["reading_guide"]
    assert len(payload["steps"]) == 2
    assert len(payload["steps"][0]["evidence"]) == 2
    assert len(payload["steps"][0]["related"]) == 2
    assert len(payload["gaps"]) == 2
    assert payload["truncated"] is True


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_repository_text_cannot_change_markdown_structure(
    reading_report: RepositoryReport, detail: str,
) -> None:
    """路径、文本和代码围栏中的特殊字符保留原意，不注入报告结构。"""
    preview = "```\n## Git 历史\n<script>unsafe()</script>\n````"
    step = reading_report.reading_guide.steps[0]
    reading_report.reading_guide.steps = [replace(
        step,
        question="[点击](https://example.invalid)\n## 注入标题 | `x`",
        location=ReadingLocation("src/a|`b`.py", 2, 4, preview),
        summary="<script>alert(1)</script>",
        related=(ReadingLocation("notes.md", 4, excerpt="## Git 历史"),),
    )]
    markdown = MarkdownRenderer().render(reading_report, detail=detail)
    assert "src/a\\|\\`b\\`.py:2-4" in markdown
    assert "&lt;script&gt;alert\\(1\\)&lt;/script&gt;" in markdown
    if detail == "full":
        assert "\\[点击\\]\\(https://example.invalid\\)" in markdown
        assert "`````text\n" + preview + "\n`````" in markdown
        assert "```text\n## Git 历史\n```" in markdown
        assert "### 分析说明" in markdown
    else:
        assert "```" not in _guide_section(markdown)
    assert "\n## 注入标题" not in markdown
    payload = json.loads(JsonRenderer().render(reading_report))["reading_guide"]
    assert payload["steps"][0]["location"]["excerpt"] == preview
    assert payload["steps"][0]["location"]["path"] == "src/a|`b`.py"


def test_partial_error_remains_visible(reading_report: RepositoryReport) -> None:
    """保留部分结果时，原始错误与警告不会因存在步骤而消失。"""
    reading_report.analyzer_results[AnalyzerName.READING] = AnalysisResult(
        AnalyzerName.READING, status=AnalyzerStatus.FAILED,
        reason="一部分来源无法读取", warnings=["缺少文档"], errors=["读取中断"],
    )
    payload = json.loads(JsonRenderer().render(reading_report))["reading_guide"]
    assert payload["errors"] == ["读取中断"]
    assert payload["warnings"] == ["缺少文档"]
    assert len(payload["steps"]) == 1
    guide = _guide_section(MarkdownRenderer().render(reading_report))
    assert "部分结果" in guide
    assert "缺少文档" in guide
    assert "读取中断" in guide
    assert "线索 1" in guide


def test_location_without_range_has_single_line() -> None:
    """只有起始行或起止相同时不显示虚假的行号范围。"""
    assert format_location(ReadingLocation("api.py", 5)) == "api.py:5"
    assert format_location(ReadingLocation("api.py", 5, 5)) == "api.py:5"


def test_full_deduplicates_only_identical_preview_locations(
    reading_report: RepositoryReport,
) -> None:
    """去重相同片段，同时保留每条依据、不同内容和不同来源。"""
    step = reading_report.reading_guide.steps[0]
    location = step.location
    reading_report.reading_guide.steps = [replace(
        step,
        evidence=(
            ReadingEvidence("document_section", location, "第一条说明"),
            ReadingEvidence("document_link", location, "第二条说明"),
            ReadingEvidence("document_link", replace(location, excerpt="another_snapshot()"), "不同内容"),
        ),
        related=(location, replace(location, path="other/usage.md")),
    )]
    guide = _guide_section(MarkdownRenderer().render(reading_report, detail="full"))
    assert guide.count("```text\nsample.open()\n```") == 2
    assert guide.count("```text\nanother_snapshot()\n```") == 1
    for description in ("第一条说明", "第二条说明", "不同内容"):
        assert description in guide
    assert "other/usage.md:3-12" in guide
