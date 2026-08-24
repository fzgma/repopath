"""循环依赖测试模块 B。"""

import pkg.a  # pyright: ignore[reportUnusedImport]


def value() -> str:
    """返回循环依赖测试值。"""
    return "value"
