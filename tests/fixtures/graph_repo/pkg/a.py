"""循环依赖测试模块 A。"""

import pkg.b


def run() -> str:
    """调用循环依赖模块 B。"""
    return pkg.b.value()
