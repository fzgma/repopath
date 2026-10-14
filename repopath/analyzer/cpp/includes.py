"""从源码提取 include 和条件分支，仅在已扫描路径中匹配候选。"""

import os
import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ...model.cpp import CppInclude

_SPLICE = re.compile(r"\\\r?\n")
_RAW_STRING = re.compile(r'(?:u8|u|U|L)?R"([^\s()\\]{0,16})\(')
_STRING = re.compile(r"(?:u8|u|U|L)?([\"'])")
_DIRECTIVE = re.compile(r"[ \t\f\v\r]*#[ \t]*([A-Za-z_]\w*)(.*)")


@dataclass
class CppSource:
    """保存屏蔽后的逻辑源码，并将匹配位置映射回物理行与条件。"""

    code: str
    includes: list[CppInclude]
    _physical_lines: list[int] = field(repr=False)
    _logical_lines: list[int] = field(repr=False)
    _conditions: list[tuple[str, ...]] = field(repr=False)
    _splice_offsets: list[int] = field(repr=False)
    _splice_lengths: list[int] = field(repr=False)

    def location(self, offset: int) -> tuple[int, tuple[str, ...]]:
        """返回逻辑源码偏移对应的原文件行号及未求值条件。"""
        if not 0 <= offset <= len(self.code):
            raise ValueError("源码偏移超出范围")
        splice = bisect_right(self._splice_offsets, offset) - 1
        physical = offset + (self._splice_lengths[splice] if splice >= 0 else 0)
        line = bisect_right(self._physical_lines, physical)
        logical_line = bisect_right(self._logical_lines, offset) - 1
        return line, self._conditions[logical_line]


@dataclass
class _Conditional:
    """记录同一条件组的已有分支，避免将 else 误认为无条件代码。"""

    branches: list[str]
    current: str


def _apply_splices(
    source: str, matches: list[re.Match[str]],
) -> tuple[str, list[int], list[int]]:
    """移除已确认的续行，同时保存逻辑偏移到原文的增量映射。"""
    parts: list[str] = []
    offsets: list[int] = []
    lengths: list[int] = []
    previous = 0
    removed = 0
    for match in matches:
        parts.append(source[previous:match.start()])
        offsets.append(match.start() - removed)
        removed += match.end() - match.start()
        lengths.append(removed)
        previous = match.end()
    parts.append(source[previous:])
    return "".join(parts), offsets, lengths


def _splice_lines(source: str) -> tuple[str, list[int], list[int]]:
    """拼接逻辑行，但按原始文本确定 raw string 结束位置并保留其续行。"""
    matches = list(_SPLICE.finditer(source))
    logical, offsets, lengths = _apply_splices(source, matches)
    if not matches:
        return logical, offsets, lengths
    ends = [match.end() for match in matches]
    raw_ranges: list[tuple[int, int]] = []

    def raw_end(raw: re.Match[str]) -> int:
        """将开括号映射到原文，防止拼接制造不存在的 raw string 结束符。"""
        opening = raw.end() - 1
        index = bisect_right(offsets, opening) - 1
        start = opening + (lengths[index] if index >= 0 else 0) + 1
        ending = f'){raw.group(1)}"'
        closing = source.find(ending, start)
        end = len(source) if closing < 0 else closing + len(ending)
        raw_ranges.append((start, end))
        index = bisect_right(ends, end) - 1
        return end - (lengths[index] if index >= 0 else 0)

    _mask_literals(logical, raw_end=raw_end)
    if not raw_ranges:
        return logical, offsets, lengths
    starts = [start for start, _ in raw_ranges]
    retained: list[re.Match[str]] = []
    for match in matches:
        index = bisect_right(starts, match.start()) - 1
        if index < 0 or match.start() >= raw_ranges[index][1]:
            retained.append(match)
    return _apply_splices(source, retained)


def _blank(text: list[str], start: int, end: int) -> None:
    """屏蔽词法内容，保留换行及其余字符的偏移。"""
    for index in range(start, end):
        if text[index] not in "\r\n":
            text[index] = " "


def _mask_literals(
    source: str, *, raw_end: Callable[[re.Match[str]], int] | None = None,
) -> tuple[str, list[str]]:
    """分别生成保留字符串的指令原文与屏蔽字符串的结构文本。"""
    comments = list(source)
    code = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = len(source) if end < 0 else end
            _blank(comments, index, end)
            _blank(code, index, end)
            index = end
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            end = len(source) if closing < 0 else closing + 2
            _blank(comments, index, end)
            _blank(code, index, end)
            index = end
            continue
        if source[index].isdigit():
            # 数字分隔符属于数值 token；普通字符字面量仍可紧邻 return。
            index += 1
            while index < len(source):
                char = source[index]
                if (
                    char.isalnum() or char in "_."
                    or (char == "'" and index + 1 < len(source)
                        and source[index + 1].isalnum())
                    or (char in "+-" and source[index - 1] in "eEpP")
                ):
                    index += 1
                else:
                    break
            continue
        boundary = index == 0 or not (
            source[index - 1].isalnum() or source[index - 1] == "_"
        )
        raw = _RAW_STRING.match(source, index) if boundary else None
        if raw is not None:
            ending = f'){raw.group(1)}"'
            closing = source.find(ending, raw.end())
            end = (
                raw_end(raw) if raw_end is not None
                else len(source) if closing < 0 else closing + len(ending)
            )
            _blank(code, index, end)
            index = end
            continue
        literal = _STRING.match(source, index) if boundary else None
        # 普通字符串和字符字面量均可紧邻其他 token。
        if literal is None and source[index] in "\"'":
            literal = _STRING.match(source, index)
        if literal is not None:
            quote = literal.group(1)
            end = literal.end()
            while end < len(source) and source[end] not in "\r\n":
                if source[end] == "\\":
                    end += 2
                elif source[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
            end = min(end, len(source))
            _blank(code, index, end)
            index = end
            continue
        index += 1
    return "".join(comments), code


def _update_conditions(
    frames: list[_Conditional], directive: str, expression: str,
) -> None:
    """保留分支选择条件，不假定本机平台、宏值或任一分支被启用。"""
    if directive in {"elifdef", "elifndef"}:
        expression = f"{'!' if directive == 'elifndef' else ''}defined({expression})"
        directive = "elif"
    if directive in {"if", "ifdef", "ifndef"}:
        if directive == "ifdef":
            expression = f"defined({expression})"
        elif directive == "ifndef":
            expression = f"!defined({expression})"
        frames.append(_Conditional([expression], expression))
    elif frames and directive in {"elif", "else"}:
        frame = frames[-1]
        parts = [f"!({branch})" for branch in frame.branches]
        if directive == "elif":
            parts.append(f"({expression})")
            frame.branches.append(expression)
        frame.current = " && ".join(parts)
    elif frames and directive == "endif":
        frames.pop()


def _include(expression: str, line: int, conditions: tuple[str, ...]) -> CppInclude:
    """区分文字头文件名与宏表达式，不展开宏或求值。"""
    if expression.startswith('"'):
        closing = expression.find('"', 1)
        if closing >= 0:
            return CppInclude(expression[1:closing], line, "quoted", conditions)
    elif expression.startswith("<"):
        closing = expression.find(">", 1)
        if closing >= 0:
            return CppInclude(expression[1:closing], line, "angled", conditions)
    return CppInclude(expression, line, "macro", conditions, resolution="macro")


def scan_source(source: str) -> CppSource:
    """提取所有条件分支中的 include，为结构识别屏蔽注释、字面量和指令。"""
    logical, splice_offsets, splice_lengths = _splice_lines(source)
    comments, code = _mask_literals(logical)
    physical_lines = [0, *(match.end() for match in re.finditer("\n", source))]
    logical_lines = [0, *(match.end() for match in re.finditer("\n", logical))]
    conditions: list[tuple[str, ...]] = []
    includes: list[CppInclude] = []
    frames: list[_Conditional] = []
    for number, start in enumerate(logical_lines):
        end = logical_lines[number + 1] if number + 1 < len(logical_lines) else len(logical)
        active = tuple(frame.current for frame in frames)
        conditions.append(active)
        # 在屏蔽文本中识别指令起点，防止 raw string 内的 #include 泄漏。
        if _DIRECTIVE.match("".join(code[start:end])) is None:
            continue
        match = _DIRECTIVE.match(comments[start:end])
        if match is None:
            continue
        directive, expression = match.group(1), match.group(2).strip()
        if directive == "include":
            offset = start + comments[start:end].index("#")
            splice = bisect_right(splice_offsets, offset) - 1
            physical = offset + (splice_lengths[splice] if splice >= 0 else 0)
            includes.append(_include(expression, bisect_right(physical_lines, physical), active))
        _update_conditions(frames, directive, expression)
        _blank(code, start, end)
    return CppSource(
        "".join(code), includes, physical_lines, logical_lines, conditions,
        splice_offsets, splice_lengths,
    )


def _normalize(parts: tuple[str, ...]) -> tuple[str, ...] | None:
    """规范化相对路径，拒绝越过仓库根目录。"""
    normalized: list[str] = []
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not normalized:
                return None
            normalized.pop()
        else:
            normalized.append(part)
    return tuple(normalized)


class IncludeResolver:
    """预建仓库路径与完整后缀索引，匹配只依赖扫描集合且区分大小写。"""

    def __init__(self, root: Path, paths: list[Path]) -> None:
        self.root = Path(os.path.abspath(root))
        self._paths: dict[tuple[str, ...], Path] = {}
        self._suffixes: dict[tuple[str, ...], list[Path]] = {}
        for path in paths:
            absolute = Path(os.path.abspath(path if path.is_absolute() else self.root / path))
            try:
                parts = absolute.relative_to(self.root).parts
            except ValueError:
                continue
            if parts in self._paths:
                continue
            self._paths[parts] = absolute
            for index in range(len(parts)):
                self._suffixes.setdefault(parts[index:], []).append(absolute)
        for candidates in self._suffixes.values():
            candidates.sort(key=lambda path: path.as_posix())

    def resolve(self, source_path: Path, include: CppInclude) -> None:
        """优先当前文件相对路径，其次仓库路径，最后保留完整后缀候选。"""
        include.target = None
        include.candidates = []
        include.resolution = "macro" if include.kind == "macro" else "unresolved"
        if include.kind == "macro":
            return
        name = include.name.replace("\\", "/")
        if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            return
        parts = tuple(name.split("/"))
        if include.kind == "quoted":
            absolute = Path(os.path.abspath(
                source_path if source_path.is_absolute() else self.root / source_path
            ))
            try:
                parent = absolute.parent.relative_to(self.root).parts
            except ValueError:
                parent = None
            if parent is not None:
                relative = _normalize((*parent, *parts))
                if relative is not None and relative in self._paths:
                    include.target = self._paths[relative]
                    include.resolution = "relative"
        normalized = _normalize(parts)
        if include.target is None and normalized is not None:
            target = self._paths.get(normalized)
            if target is not None:
                include.target = target
                include.resolution = "repository"
            else:
                include.candidates = self._suffixes.get(normalized, []).copy()
                if len(include.candidates) == 1:
                    include.target = include.candidates[0]
                    include.resolution = "suffix"
                elif include.candidates:
                    include.resolution = "ambiguous"
        if include.target is not None:
            include.candidates = [include.target]
