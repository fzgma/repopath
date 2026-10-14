"""导读分析共用的读取边界、证据位置和公平选择。"""

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..core.context import AnalysisContext
from ..model.reading import (
    ReadingEvidence,
    ReadingGap,
    ReadingGuide,
    ReadingLocation,
    ReadingStep,
)
from ..model.result import AnalysisState

MAX_FILES = 512
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_CANDIDATES = 2000
MAX_FILE_CANDIDATES = 64
MAX_GAPS = 100
MAX_FACTS = 10000
PREVIEW_LINES = 8
PREVIEW_CHARS = 1000


@dataclass(frozen=True)
class Anchor:
    """保存文档或清单明确指向的文件与可选符号。"""

    path: str
    topic: str
    evidence: ReadingEvidence
    symbol: str = ""
    line: int | None = None
    end_line: int | None = None


class ReadingCollector:
    """只读取已扫描且解析后仍在仓库内的有限文本。"""

    def __init__(self, context: AnalysisContext, state: AnalysisState) -> None:
        """建立已扫描路径索引及一次运行内的文本、位置缓存。"""
        self.context = context
        self.root = context.repository.root.resolve()
        self.guide = ReadingGuide()
        self.paths: dict[str, Path] = {}
        self.cache: dict[str, str | None] = {}
        self._lines: dict[str, list[str]] = {}
        self.candidates: dict[tuple[str, str, int, str, str], ReadingStep] = {}
        self.anchors: list[Anchor] = []
        self.anchors_by_path: dict[str, list[Anchor]] = defaultdict(list)
        self._anchor_keys: set[
            tuple[str, str, str, int | None, int | None]
        ] = set()
        self._candidate_counts: dict[str, int] = defaultdict(int)
        self._relations = 0
        self.read_bytes = 0
        self._gap_keys: set[tuple[str, str | None]] = set()
        for record in state.artifacts.files:
            self.check_cancelled()
            path = record.path
            try:
                relative = path.relative_to(self.root).as_posix()
                if not path.resolve().is_relative_to(self.root):
                    self.gap(
                        "outside_root",
                        "跳过解析后位于仓库外的文件。",
                        relative,
                    )
                    continue
            except (OSError, RuntimeError, ValueError):
                self.gap("outside_root", "跳过不在仓库范围内的文件。")
                continue
            self.paths[relative] = path

    def check_cancelled(self) -> None:
        """在文件、候选和语法遍历之间响应取消。"""
        self.context.cancellation.raise_if_cancelled()

    def gap(self, kind: str, message: str, path: str | None = None) -> None:
        """合并同一文件的同类缺口，防止错误输出无限增长。"""
        if kind in {
            "read_budget",
            "fact_budget",
            "candidate_budget",
            "relation_budget",
            "related_limit",
            "selection_limit",
            "gap_limit",
        }:
            self.guide.truncated = True
        key = (kind, path)
        if key in self._gap_keys:
            return
        self._gap_keys.add(key)
        if len(self.guide.gaps) < MAX_GAPS:
            self.guide.gaps.append(ReadingGap(kind, message, path))
        elif not any(item.kind == "gap_limit" for item in self.guide.gaps):
            self.guide.truncated = True
            self.guide.gaps.append(ReadingGap("gap_limit", "其余缺口已省略。"))

    def read(self, path: str) -> str | None:
        """读取前验证路径和大小；总量、单文件和文件数均有上限。"""
        self.check_cancelled()
        if path in self.cache:
            return self.cache[path]
        actual = self.paths.get(path)
        if actual is None:
            return None
        if len(self.cache) >= MAX_FILES:
            self.guide.truncated = True
            self.gap("read_budget", "导读读取文件数达到上限，未覆盖全部证据。")
            return None
        self.cache[path] = None
        try:
            if not actual.resolve().is_relative_to(self.root):
                self.gap(
                    "outside_root", "文件解析后位于仓库外，未读取。", path
                )
                return None
            size = actual.stat().st_size
            if (
                size > MAX_FILE_BYTES
                or self.read_bytes + size > MAX_TOTAL_BYTES
            ):
                self.guide.truncated = True
                self.gap(
                    "read_budget",
                    "文件超过单次导读读取预算，未截取为完整语法。",
                    path,
                )
                return None
            source = self.context.filesystem.read_text(actual)
        except (OSError, UnicodeError, ValueError, RuntimeError):
            source = None
        if source is None:
            self.gap("unreadable", "无法读取文本，保留其他文件的证据。", path)
            return None
        size = len(source.encode("utf-8", errors="replace"))
        if size > MAX_FILE_BYTES or self.read_bytes + size > MAX_TOTAL_BYTES:
            self.guide.truncated = True
            self.gap("read_budget", "解码后的文本超过导读预算，已跳过。", path)
            return None
        self.read_bytes += size
        self.guide.scanned_files += 1
        self.cache[path] = source
        return source

    def location(
        self,
        path: str,
        line: int = 1,
        end_line: int | None = None,
    ) -> ReadingLocation:
        """返回相对位置和有界预览；范围末行可以超出预览。"""
        lines = self.lines(path)
        line = min(max(1, line), max(1, len(lines)))
        if end_line is not None:
            end_line = min(max(line, end_line), max(1, len(lines)))
        stop = min(
            end_line or line + PREVIEW_LINES - 1, line + PREVIEW_LINES - 1
        )
        excerpt = "\n".join(lines[line - 1 : stop])[:PREVIEW_CHARS]
        return ReadingLocation(path, line, end_line, excerpt)

    def lines(self, path: str) -> list[str]:
        """复用拆行结果，避免同文件多条证据反复遍历整份文本。"""
        if path not in self._lines:
            source = self.read(path)
            self._lines[path] = (
                source.splitlines() if source is not None else []
            )
        return self._lines[path]

    def resolve(self, source: str, target: str) -> tuple[str, str] | None:
        """解析本地显式链接；禁止绝对路径、网络和扫描范围外文件。"""
        try:
            parsed = urlsplit(target)
        except ValueError:
            self.gap("unresolved_link", "链接格式无法识别。", source)
            return None
        if parsed.scheme or parsed.netloc:
            return None
        raw = unquote(parsed.path)
        if "\\" in raw or raw.startswith("/") or "\x00" in raw:
            self.gap(
                "outside_link", "未跟随绝对路径或非相对路径链接。", source
            )
            return None
        base = Path(source).parent
        parts: list[str] = []
        for part in (base / raw).parts if raw else Path(source).parts:
            if part == "..":
                if not parts:
                    self.gap("outside_link", "未跟随仓库外链接。", source)
                    return None
                parts.pop()
            elif part not in {".", ""}:
                parts.append(part)
        path = "/".join(parts)
        if path not in self.paths:
            self.gap(
                "unresolved_link", "显式链接的目标不在已扫描文件中。", source
            )
            return None
        return path, unquote(parsed.fragment)

    def add(
        self,
        *,
        topic: str,
        kind: str,
        question: str,
        summary: str,
        location: ReadingLocation,
        evidence: tuple[ReadingEvidence, ...],
        confidence: str = "observed",
        related: tuple[ReadingLocation, ...] = (),
    ) -> None:
        """保存候选；重复事实不会增加候选数量或选择机会。"""
        self.check_cancelled()
        key = (kind, location.path, location.line, topic, summary)
        if key in self.candidates:
            return
        if self._candidate_counts[location.path] >= MAX_FILE_CANDIDATES:
            self.guide.truncated = True
            self.gap(
                "candidate_budget",
                "单文件候选达到上限，为其他文件保留分析空间。",
                location.path,
            )
            return
        if len(self.candidates) >= MAX_CANDIDATES:
            self.guide.truncated = True
            self.gap("candidate_budget", "导读候选达到上限，未覆盖全部证据。")
            return
        self._candidate_counts[location.path] += 1
        if len(related) > 6:
            self.gap(
                "related_limit",
                "单步仅保留前 6 个关联位置，其余候选未保存，不代表已排除。",
                location.path,
            )
        self.candidates[key] = ReadingStep(
            id=f"{kind}:{location.path}:{location.line}:{len(self.candidates)}",
            topic=topic,
            kind=kind,
            question=question,
            summary=summary,
            location=location,
            confidence=confidence,
            evidence=evidence,
            related=related[:6],
        )

    def anchor(self, anchor: Anchor) -> None:
        """同一来源重复链接不放大目标文件的候选机会。"""
        key = (
            anchor.path,
            anchor.topic,
            anchor.symbol,
            anchor.line,
            anchor.end_line,
        )
        if key in self._anchor_keys:
            return
        if len(self.anchors) >= MAX_FACTS:
            self.guide.truncated = True
            self.gap("fact_budget", "显式引用数量达到导读预算。")
            return
        self._anchor_keys.add(key)
        self.anchors.append(anchor)
        self.anchors_by_path[anchor.path].append(anchor)

    def relation(self) -> bool:
        """限制跨来源关联尝试，避免重复声明和引用形成无界笛卡尔积。"""
        self.check_cancelled()
        self._relations += 1
        if self._relations <= MAX_FACTS:
            return True
        self.guide.truncated = True
        self.gap("relation_budget", "跨来源关联达到数量上限，尚有关系未检查。")
        return False

    def select(self, limit: int) -> ReadingGuide:
        """在证据类别、主题和文件间轮询，不按符号数量或热度排序。"""
        groups: dict[str, dict[str, deque[ReadingStep]]] = defaultdict(dict)
        candidate_keys: set[tuple[str, str, int, str]] = set()
        for step in self.candidates.values():
            groups[step.kind].setdefault(step.topic, deque()).append(step)
            candidate_keys.add(
                (
                    step.kind,
                    step.location.path,
                    step.location.line,
                    step.summary,
                )
            )
        queues = {
            kind: deque(deque(values) for values in topics.values())
            for kind, topics in groups.items()
        }
        selected: set[tuple[str, str, int, str]] = set()
        used_paths: dict[str, int] = defaultdict(int)
        kinds = [
            kind
            for kind in ("document", "interface", "definition", "usage")
            if kind in queues
        ]
        while kinds and len(self.guide.steps) < limit:
            self.check_cancelled()
            for kind in kinds[:]:
                topics = queues[kind]
                # 每轮优先尚未出现的目标文件；排序仅稳定展示，不表示价值高低。
                if topics:
                    minimum = min(
                        used_paths[items[0].location.path] for items in topics
                    )
                    while used_paths[topics[0][0].location.path] != minimum:
                        topics.rotate(-1)
                items = topics.popleft()
                step = items.popleft()
                key = (
                    step.kind,
                    step.location.path,
                    step.location.line,
                    step.summary,
                )
                if key not in selected:
                    selected.add(key)
                    used_paths[step.location.path] += 1
                    self.guide.steps.append(step)
                if items:
                    topics.append(items)
                if not topics:
                    kinds.remove(kind)
                if len(self.guide.steps) >= limit:
                    break
        # 同一片段被多个主题引用只算一个候选；去重不属于预算截断。
        self.guide.candidate_count = len(candidate_keys)
        if self.guide.candidate_count > len(self.guide.steps):
            self.gap(
                "selection_limit",
                "按类别和主题轮询展示有限步骤；其余候选未显示，不代表不重要。",
            )
        if not self.guide.steps:
            self.gap(
                "no_evidence",
                "未找到足以形成导读的文档、显式入口、导出或有说明的符号；未用规模和热度补齐。",
            )
        return self.guide
