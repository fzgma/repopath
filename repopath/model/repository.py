"""仓库路径模型。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Repository:
    """表示一个待分析的本地代码仓库。"""

    root: Path

    @classmethod
    def from_path(cls, path: str | Path) -> "Repository":
        """规范化路径并创建仓库对象。"""
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"仓库目录不存在：{root}")
        return cls(root=root)

    @property
    def name(self) -> str:
        """返回仓库目录名称。"""
        return self.root.name

    def relative_path(self, path: Path) -> str:
        """将仓库内文件路径转换为报告使用的相对路径。"""
        return path.resolve().relative_to(self.root).as_posix()
