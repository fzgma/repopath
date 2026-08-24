"""多语言仓库分析和 Renderer 测试。"""

import json
from pathlib import Path

from repopath.core.service import analyze_repository
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mixed_repo"


def test_mixed_repository_report_contains_python_and_cpp_sections() -> None:
    """验证混合仓库报告保留 Python 和 C++ 结果。"""
    report = analyze_repository(FIXTURE_ROOT)
    markdown = MarkdownRenderer().render(report)
    payload = json.loads(JsonRenderer().render(report))

    assert report.stats.language_family_counts["Python"] == 5
    assert report.stats.language_family_counts["C++"] == 3
    assert "## C++ 分析" in markdown
    assert payload["cpp"]["file_count"] == 3
    assert payload["python"]["function_count"] == 5
    assert payload["schema_version"] == "0.3"
    assert payload["overview"]["dependency_nodes"] == 8
    assert payload["insights"]["reading_order"]
    assert "## 推荐阅读顺序" in markdown
    assert any(edge["kind"] == "include" for edge in payload["dependencies"]["edges"])
    assert any(edge["kind"] == "import" for edge in payload["dependencies"]["edges"])
    assert isinstance(payload["directories"]["pkg"], int)
    assert payload["directory_stats"]["pkg"]["files"] == 3
