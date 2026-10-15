"""验证文档摘录、组成线索和来源位置，不评判实际阅读价值。"""

import json
from pathlib import Path

from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


def _write(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _analyze(root: Path, limit: int = 10):
    return analyze_repository(
        root,
        options=AnalysisOptions(
            reading_enabled=True,
            reading_limit=limit,
            git_enabled=False,
            dependencies_enabled=False,
            insights_enabled=False,
        ),
    )


def test_manifest_readme_and_components_keep_source_records(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname="vectors"\ndescription="Convert point collections."\nreadme="notes/contract.md"\n[project.scripts]\nconvert="engine:main"\n',
            "notes/contract.md": "# Vectors\nConvert point collections between coordinate systems.\n\n## Architecture\nThe kernel transforms points and the gateway handles requests.\n\n## Usage\n[Example](../example.py)\n",
            "engine.py": 'def debug():\n    """Print internal status."""\n    pass\n\ndef main():\n    """Read input and invoke the conversion."""\n    pass\n',
            "kernel/__init__.py": '"""Coordinate transformations with no transport logic."""\n',
            "gateway/package.json": '{"name":"gateway","description":"Receive requests and return converted points."}',
            "example.py": "from engine import main\nmain()\n",
        },
    )
    report = _analyze(tmp_path)
    guide = report.reading_guide
    assert any(
        item.description == "Convert point collections."
        and item.location.path == "pyproject.toml"
        for item in guide.purpose
    )
    assert any("kernel transforms" in item.description for item in guide.structure)
    assert {item.path for item in guide.components} >= {"kernel", "gateway"}
    assert any("no transport" in item.summary for item in guide.components)
    assert any(
        step.location.path == "engine.py" and step.location.line == 5
        for step in guide.steps
    )
    assert not any(
        step.location.path == "engine.py" and step.location.line == 1
        for step in guide.steps
    )
    assert all(step.reason and step.learn for step in guide.steps)
    payload = json.loads(JsonRenderer().render(report))["reading_guide"]
    assert {
        (item["description"], item["location"]["path"])
        for item in payload["purpose"]
    } == {(item.description, item.location.path) for item in guide.purpose}
    assert len(payload["components"]) == len(guide.components)
    for detail in ("summary", "full"):
        markdown = MarkdownRenderer().render(report, detail=detail)
        for phrase in (
            "1. 项目说明摘录",
            "2. 组成线索",
            "3. 阅读线索",
            "列出依据",
            "可核对内容",
            "Convert point collections.",
        ):
            assert phrase in markdown


def test_unrelated_documents_and_documented_functions_do_not_replace_public_usage(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        {
            "README.md": "# Translation library\nConvert structured records into portable messages.\n",
            "kernel.py": '__all__ = ["convert"]\ndef convert(value):\n    """Convert a record."""\n    return value\n',
            "example.py": 'from kernel import convert\nconvert("input")\n',
        },
    )
    before = _analyze(tmp_path).reading_guide
    _write(
        tmp_path,
        {
            **{
                f".github/form{i}.md": "# Submission form\nDescribe your change here.\n"
                for i in range(40)
            },
            **{
                f"noise/part{i}.py": "\n".join(
                    f'def helper{j}():\n    """Explain an internal helper."""\n    pass\n'
                    for j in range(64)
                )
                for i in range(34)
            },
        },
    )
    after = _analyze(tmp_path).reading_guide
    assert all(item in after.purpose for item in before.purpose)
    assert any(
        s.kind == "usage" and s.location.path == "example.py" for s in after.steps
    )
    assert not any(g.kind == "candidate_budget" for g in after.gaps)


def test_many_public_interfaces_do_not_exhaust_later_usage_candidates(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        {
            "README.md": "# Public contracts\nA collection of independently usable transformations.\n",
            "zz_core.py": '__all__ = ["work"]\ndef work(value):\n    return value\n',
            "zz_use.py": "from zz_core import work\nwork(1)\n",
            **{
                f"apis/part{i}.py": "__all__ = ["
                + ",".join(f'"f{j}"' for j in range(64))
                + "]\n"
                + "\n".join(f"def f{j}(x):\n    return x\n" for j in range(64))
                for i in range(34)
            },
        },
    )
    guide = _analyze(tmp_path).reading_guide
    assert guide.truncated
    assert any(
        s.kind == "usage" and s.location.path == "zz_use.py" for s in guide.steps
    )


def test_manifest_entries_are_grouped_without_hiding_later_commands(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        {
            "pyproject.toml": '[project.scripts]\nrelease="tools:publish"\nserve="server:start"\n',
            "tools.py": "def publish():\n    pass\n",
            "server.py": "def start():\n    pass\n",
        },
    )
    guide = _analyze(tmp_path).reading_guide
    declaration = next(s for s in guide.steps if s.location.path == "pyproject.toml")
    assert "release" in declaration.summary and "serve" in declaration.summary
    assert {item.location.path for item in declaration.evidence} == {"pyproject.toml"}
    assert {location.path for location in declaration.related} == {
        "tools.py",
        "server.py",
    }


def test_no_business_roles_are_invented_from_directory_names(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "payments/__init__.py": "",
            "auth/__init__.py": "",
            "utils/tool.py": "x = 1\n",
        },
    )
    guide = _analyze(tmp_path).reading_guide
    assert not guide.purpose
    assert {item.path for item in guide.components} == {"payments", "auth", "utils"}
    assert all(not item.evidence for item in guide.components)
    assert not guide.steps


def test_explicit_script_guard_is_useful_without_docstrings_or_manifest(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        {
            "unusual.py": 'def launch():\n    pass\n\nif __name__ == "__main__":\n    launch()\n'
        },
    )
    guide = _analyze(tmp_path).reading_guide
    entry = next(s for s in guide.steps if s.goal == "entry")
    assert entry.location.line == 4
    assert entry.related[0].line == 1


def test_unknown_language_subproject_uses_author_description(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "package.json": '{"name":"schema-set","description":"Shared message definitions."}',
            "protocol/package.json": '{"name":"wire-format","description":"Versioned transport schemas.","exports":"./messages.proto"}',
            "protocol/messages.proto": 'syntax = "proto3";\nmessage Record {}\n',
        },
    )
    guide = _analyze(tmp_path).reading_guide
    assert guide.purpose[0].description == "Shared message definitions."
    assert guide.components[0].summary == "Versioned transport schemas."
    assert any(
        item.path == "protocol/messages.proto"
        for s in guide.steps
        for item in s.related
    )


def test_project_sections_and_entry_survive_many_feature_documents(
    tmp_path: Path,
) -> None:
    """组件文档中的功能标题不能抢占全项目的介绍与入口。"""
    _write(
        tmp_path,
        {
            "README.md": "# Overview\nA server for transforming structured input records.\n\n## Architecture\nThe gateway delegates transformations to the engine.\n[Contributing](CONTRIBUTING.md)\n",
            "pyproject.toml": '[project.scripts]\nstart="runner:main"\n',
            "runner.py": "def main():\n    pass\n",
            "AGENTS.md": "# Usage\nAlways invoke the development helper before editing.\n",
            "CONTRIBUTING.md": "# Usage\nAlways submit changes through the review form.\n",
            **{
                f"part{i}/README.md": "# Component\n## Features\nThis component provides many optional features.\n"
                for i in range(30)
            },
        },
    )
    guide = _analyze(tmp_path).reading_guide
    assert any(
        s.goal == "structure" and s.location.path == "README.md" for s in guide.steps
    )
    assert any(
        s.goal == "entry" and s.location.path == "runner.py" for s in guide.steps
    )
    assert not any(
        s.location.path in {"AGENTS.md", "CONTRIBUTING.md"} for s in guide.steps
    )


def test_public_reexport_connects_package_usage_to_implementation(
    tmp_path: Path,
) -> None:
    """包级接口、实际实现和使用示例一起定位，避免只列 __all__。"""
    _write(
        tmp_path,
        {
            "kit/__init__.py": 'from .engine import transform as convert\n__all__ = ["convert"]\n',
            "kit/engine.py": 'def transform(value):\n    """Convert one record."""\n    return value\n',
            "sample.py": "from kit import convert\nconvert(1)\n",
        },
    )
    guide = _analyze(tmp_path).reading_guide
    usage = next(s for s in guide.steps if s.kind == "usage")
    assert usage.location.path == "sample.py"
    assert usage.related[0].path == "kit/engine.py"
    assert not any(g.kind == "unresolved_export" for g in guide.gaps)


def test_cyclic_or_rebound_exports_do_not_create_usage_links(tmp_path: Path) -> None:
    """不能因追踪重导出而绕过原有歧义和重绑定检查。"""
    _write(
        tmp_path,
        {
            "first.py": 'from second import call\n__all__ = ["call"]\n',
            "second.py": 'from first import call\n__all__ = ["call"]\n',
            "changed.py": 'from actual import call\ncall = object()\n__all__ = ["call"]\n',
            "actual.py": "def call():\n    pass\n",
            "use.py": "from first import call\nfrom changed import call as other\ncall()\nother()\n",
        },
    )
    guide = _analyze(tmp_path).reading_guide
    assert not any(s.kind == "usage" for s in guide.steps)
    assert any(g.kind == "unresolved_export" for g in guide.gaps)


def test_exported_entry_keeps_startup_evidence_when_grouped(tmp_path: Path) -> None:
    """同一启动函数被公开导出时，合并片段仍保留入口身份。"""
    _write(
        tmp_path,
        {
            "runner.py": '__all__ = ["launch"]\ndef launch():\n    pass\n\nif __name__ == "__main__":\n    launch()\n',
        },
    )
    guide = _analyze(tmp_path).reading_guide
    entry = next(s for s in guide.steps if s.goal == "entry")
    assert entry.location.line == 2
    assert any(e.kind == "source_entry" for e in entry.evidence)
    assert any(location.line == 5 for location in entry.related)


def test_namespace_component_does_not_inherit_child_package_description(
    tmp_path: Path,
) -> None:
    """子包说明仅适用于子包，不能上推成整个目录的职责。"""
    _write(
        tmp_path,
        {
            "kit/__init__.py": "",
            "kit/extensions/remote/__init__.py": '"""Remote synchronization adapter."""\n',
        },
    )
    guide = _analyze(tmp_path).reading_guide
    parent = next(item for item in guide.components if item.path == "kit/extensions")
    assert not parent.evidence
    assert "Remote synchronization" not in parent.summary
