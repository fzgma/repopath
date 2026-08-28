"""多语言仓库分析和 Renderer 测试。"""

import json
from pathlib import Path

from repopath.core.service import analyze_repository
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mixed_repo"


def test_mixed_repository_report_contains_python_and_cpp_sections() -> (
    None
):
    """验证混合仓库报告保留 Python 和 C++ 结果。"""
    report = analyze_repository(FIXTURE_ROOT)
    markdown = MarkdownRenderer().render(report)
    payload = json.loads(JsonRenderer().render(report))

    assert report.stats.language_family_counts["Python"] == 5
    assert report.stats.language_family_counts["C++"] == 3
    assert "## C++ 分析" in markdown
    assert payload["cpp"]["file_count"] == 3
    assert payload["python"]["function_count"] == 5
    assert payload["schema_version"] == "0.4"
    assert payload["overview"]["dependency_nodes"] == 8
    assert payload["insights"]["reading_order"]
    assert "## 推荐阅读顺序" in markdown
    assert "## 文件清单" not in markdown
    assert "阅读优先级" in markdown
    assert "变更关注度" in markdown
    assert "风险分" not in markdown
    assert "hotspots" not in payload["insights"]
    assert (
        "total" not in payload["insights"]["module_scores"][0]["scores"]
    )
    score_fields = payload["insights"]["module_scores"][0]["scores"]
    assert "reading_priority_score" in score_fields
    assert "change_attention_score" in score_fields
    assert any(
        edge["kind"] == "include"
        for edge in payload["dependencies"]["edges"]
    )
    assert any(
        edge["kind"] == "import"
        for edge in payload["dependencies"]["edges"]
    )
    assert isinstance(payload["directories"]["pkg"], int)
    assert payload["directory_stats"]["pkg"]["files"] == 3


def test_markdown_file_list_is_opt_in() -> None:
    """验证 Markdown 文件清单默认关闭且可由配置选项打开。"""
    report = analyze_repository(FIXTURE_ROOT)
    report.options = report.options.with_overrides(
        include_file_list=True, reading_limit=1
    )

    markdown = MarkdownRenderer().render(report)

    assert "## 文件清单" in markdown
    assert "`python_app.py`" in markdown
