"""仓库路径模型。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path


class RepositorySourceType(StrEnum):
    """定义仓库来源类型。"""

    LOCAL = "local"
    GITHUB = "github"


@dataclass(frozen=True)
class RepositorySource:
    """描述待分析仓库的来源和位置。"""

    type: RepositorySourceType
    location: str
    reference: str | None = None

    @classmethod
    def local(cls, path: str | Path) -> "RepositorySource":
        """创建本地目录仓库来源。"""
        return cls(RepositorySourceType.LOCAL, str(path))

    @classmethod
    def github(
        cls, location: str, reference: str | None = None
    ) -> "RepositorySource":
        """创建 GitHub 公开仓库来源。"""
        return cls(RepositorySourceType.GITHUB, location, reference)


@dataclass(frozen=True)
class GitHubRateLimit:
    """保存本次 GitHub API 核心额度的快照。"""

    limit: int
    remaining: int
    reset: int

    @property
    def reset_at(self) -> datetime:
        """将 GitHub 返回的重置时间戳转换为本地时间。"""
        return datetime.fromtimestamp(
            self.reset, tz=timezone.utc
        ).astimezone()


@dataclass(frozen=True)
class Repository:
    """表示一个待分析的本地代码仓库。"""

    root: Path
    display_name: str | None = None

    @classmethod
    def from_path(cls, path: str | Path) -> "Repository":
        """规范化路径并创建仓库对象。"""
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"仓库目录不存在：{root}")
        return cls(root=root)

    @classmethod
    def from_source(cls, source: RepositorySource) -> "Repository":
        """从当前支持的仓库来源创建本地仓库模型。"""
        if source.type is not RepositorySourceType.LOCAL:
            raise NotImplementedError(
                f"暂不支持仓库来源：{source.type}"
            )
        return cls.from_path(source.location)

    @property
    def name(self) -> str:
        """返回仓库目录名称。"""
        return self.display_name or self.root.name

    def relative_path(self, path: Path) -> str:
        """将仓库内文件路径转换为报告使用的相对路径。"""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.resolve().relative_to(self.root).as_posix()
