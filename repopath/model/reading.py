"""带来源的试验性阅读指南，供 CLI 和 UI 共用。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReadingLocation:
    """记录仓库相对位置与有界预览；预览不保证包含整个范围。"""

    path: str
    line: int
    end_line: int | None = None
    excerpt: str = ""


@dataclass(frozen=True)
class ReadingEvidence:
    """说明某条阅读建议来自哪种可核查事实。"""

    kind: str
    location: ReadingLocation
    description: str


@dataclass(frozen=True)
class ReadingStep:
    """在一个主题内回答有限问题，不代表运行顺序或业务重要性。"""

    id: str
    topic: str
    kind: str
    question: str
    summary: str
    location: ReadingLocation
    confidence: str = "observed"
    evidence: tuple[ReadingEvidence, ...] = ()
    related: tuple[ReadingLocation, ...] = ()


@dataclass(frozen=True)
class ReadingGap:
    """记录未支持、读取失败、歧义或预算截断等缺口。"""

    kind: str
    message: str
    path: str | None = None


@dataclass
class ReadingGuide:
    """保存按证据选出的阅读步骤和能力边界。"""

    steps: list[ReadingStep] = field(default_factory=list)
    gaps: list[ReadingGap] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    candidate_count: int = 0
    scanned_files: int = 0
    truncated: bool = False
