"""依赖图入口测试文件。"""

import pkg.a


def main() -> None:
    """调用依赖包入口。"""
    pkg.a.run()


if __name__ == "__main__":
    main()
