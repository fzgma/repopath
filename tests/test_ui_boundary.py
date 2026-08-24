"""Streamlit UI 包依赖边界测试。"""

import ast
from pathlib import Path


def test_ui_package_does_not_import_analyzer_or_provider() -> None:
    """验证 UI 包不直接依赖 Analyzer 或 Provider 实现。"""
    ui_root = (
        Path(__file__).parents[1] / "repopath" / "interface" / "ui"
    )
    imported_modules: list[str] = []
    for path in ui_root.glob("*.py"):
        tree = ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path)
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
            ):
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(
                    alias.name for alias in node.names
                )

    assert not any(
        ".analyzer" in module or ".provider" in module
        for module in imported_modules
    )
