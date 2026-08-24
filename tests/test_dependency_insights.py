"""统一依赖图和阅读洞察测试。"""

from pathlib import Path

from repopath.core.service import analyze_repository


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "graph_repo"


def test_dependency_graph_detects_cycles_isolated_nodes_and_entry_paths() -> None:
    """验证统一依赖图可识别循环、孤立节点和入口距离。"""
    report = analyze_repository(FIXTURE_ROOT)

    assert {"python:pkg.a", "python:pkg.b"} in [set(cycle) for cycle in report.dependencies.cycles]
    assert "python:isolated" in report.dependencies.isolated_nodes
    assert "directory:pkg" in report.dependencies.directory_nodes
    assert report.dependencies.entry_nodes == ["python:entry"]
    scores = {item.node_id: item for item in report.insights.module_scores}
    assert scores["python:entry"].entry_distance == 0
    assert scores["python:pkg.a"].entry_distance == 1
    assert report.insights.reading_order[0].node_id == "python:entry"
    assert any(path.target == "python:pkg.b" for path in report.insights.reading_paths)
    assert report.insights.module_scores == sorted(
        report.insights.module_scores,
        key=lambda item: (-item.total_score, item.path),
    )


def test_reading_order_falls_back_to_scores_without_entry_points(tmp_path: Path) -> None:
    """验证无入口仓库仍能按评分生成阅读候选。"""
    (tmp_path / "module.py").write_text("def value():\n    return 1\n", encoding="utf-8")

    report = analyze_repository(tmp_path)

    assert not report.dependencies.entry_nodes
    assert report.insights.reading_order[0].path == "module.py"
    assert report.insights.reading_order[0].entry_distance is None


def test_reading_order_supports_multiple_entry_points(tmp_path: Path) -> None:
    """验证多入口仓库会优先列出全部入口模块。"""
    (tmp_path / "common.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import common\n", encoding="utf-8")
    (tmp_path / "manage.py").write_text("import common\n", encoding="utf-8")

    report = analyze_repository(tmp_path)

    assert set(report.dependencies.entry_nodes) == {"python:main", "python:manage"}
    assert {item.node_id for item in report.insights.reading_order[:2]} == {
        "python:main",
        "python:manage",
    }
