"""仓库统计结果模型。"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class RepositoryStats:
    """保存语言、代码行数和主要目录统计。"""

    language_counts: Counter[str] = field(default_factory=Counter)
    language_lines: Counter[str] = field(default_factory=Counter)
    language_comment_lines: Counter[str] = field(default_factory=Counter)
    language_family_counts: Counter[str] = field(default_factory=Counter)
    language_family_lines: Counter[str] = field(default_factory=Counter)
    directory_counts: Counter[str] = field(default_factory=Counter)
    directory_lines: Counter[str] = field(default_factory=Counter)

    @property
    def total_non_empty_lines(self) -> int:
        """返回仓库的非空行总数。"""
        return sum(self.language_lines.values())

    @property
    def total_comment_lines(self) -> int:
        """返回仓库中识别到的注释行总数。"""
        return sum(self.language_comment_lines.values())
