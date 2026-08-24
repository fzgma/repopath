"""Python fixture entry point."""

from helpers import build_message


def main() -> None:
    """运行示例入口。"""
    print(build_message())


if __name__ == "__main__":
    main()
