"""RepoPath 根目录兼容启动脚本。"""

from repopath.interface.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
