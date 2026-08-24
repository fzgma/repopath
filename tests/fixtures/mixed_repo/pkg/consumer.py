"""Relative import fixture consumer."""

from .mod import make_value


def consume() -> int:
    """使用相对导入的函数。"""
    return make_value()
