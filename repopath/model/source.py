"""跨语言静态分析的通用模型。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceSymbol:
    """表示从源码中识别出的命名符号。"""

    name: str
    kind: str
    path: Path
    line: int


@dataclass(frozen=True)
class SourceDependency:
    """表示一个文件或模块指向另一个目标的依赖。"""

    source: str
    target: str
    kind: str
