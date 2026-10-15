"""带来源的实验性阅读指南，供 CLI 和 UI 共用。"""

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
    """说明某条阅读线索来自哪种可核查事实。"""

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
    reason: str = ""
    learn: str = ""
    goal: str = ""


@dataclass(frozen=True)
class ReadingComponent:
    """由清单或源码包边界确认的组成部分，不按名称猜测职责。"""

    path: str
    name: str
    summary: str
    location: ReadingLocation
    evidence: tuple[ReadingEvidence, ...] = ()


@dataclass(frozen=True)
class ReadingGap:
    """记录未支持、读取失败、歧义或预算截断等缺口。"""

    kind: str
    message: str
    path: str | None = None


@dataclass
class ReadingGuide:
    """保存按静态规则选出的阅读线索和能力边界。"""

    steps: list[ReadingStep] = field(default_factory=list[ReadingStep])
    gaps: list[ReadingGap] = field(default_factory=list[ReadingGap])
    capabilities: list[str] = field(default_factory=list[str])
    candidate_count: int = 0
    scanned_files: int = 0
    truncated: bool = False
    purpose: list[ReadingEvidence] = field(default_factory=list[ReadingEvidence])
    structure: list[ReadingEvidence] = field(default_factory=list[ReadingEvidence])
    components: list[ReadingComponent] = field(default_factory=list[ReadingComponent])
