"""按来源和静态关系选择阅读线索，不判断实际阅读价值。"""

from collections import Counter
from dataclasses import replace

from ..model.reading import ReadingStep

GOAL_ORDER = {
    "purpose": 0,
    "structure": 1,
    "entry": 2,
    "usage": 3,
    "contract": 4,
    "implementation": 5,
    "document": 6,
    "overview": 1,
    "component": 7,
    "maintenance": 9,
}


def explain(step: ReadingStep) -> ReadingStep:
    """说明线索的提取依据及可以返回源码核对的内容。"""
    kinds = {item.kind for item in step.evidence}
    goal = step.goal
    reason, learn = step.reason, step.learn
    if not goal:
        if "manifest_entry" in kinds or "source_entry" in kinds:
            goal = "entry"
        elif "python_call_expression" in kinds or "cpp_include" in kinds:
            goal = "usage"
        elif "python_export" in kinds:
            goal = "contract"
        elif "document_link" in kinds:
            goal = "implementation"
        else:
            goal = "document"
    if not reason:
        if "manifest_entry" in kinds:
            reason = "项目清单中存在入口声明。"
            learn = "核对声明的入口及关联实现。"
        elif "source_entry" in kinds:
            reason = "源码中存在入口标记。"
            learn = "查看入口附近的代码及已定位的调用。"
        elif "python_call_expression" in kinds:
            reason = "这里存在可与导入名称关联的调用表达式。"
            learn = (
                f"查看 {step.summary.removesuffix(' 的使用候选')} 的参数和使用上下文。"
            )
        elif "python_export" in kinds:
            reason = "源码在 __all__ 中列出此名称，仅说明导出声明。"
            learn = "核对导出名称及已定位的定义；列表本身不解释具体功能。"
        elif "cpp_include" in kinds:
            reason = "此处存在关联头文件的 include 记录。"
            learn = "核对包含该头文件的源码及关联位置。"
        elif "document_link" in kinds:
            reason = "文档中存在指向此处的链接。"
            learn = "对照链接所在段落与目标文件。"
        elif step.kind == "document":
            reason = "此处存在文档或注释片段。"
            learn = step.summary
        else:
            reason = "此处存在接口或模块的说明片段。"
            learn = step.summary
    return replace(
        step, goal=goal, reason=step.reason or reason, learn=step.learn or learn
    )


def priority(step: ReadingStep) -> tuple[int, int, int, str, int, str]:
    """明确关系优先于孤立声明，路径仅用于同等依据下的稳定次序。"""
    connected = bool(step.related) or len({item.kind for item in step.evidence}) > 1
    return (
        GOAL_ORDER.get(step.goal, 7),
        step.location.path.count("/"),
        not connected,
        step.location.path,
        step.location.line,
        step.summary,
    )


def select_steps(candidates: list[ReadingStep], limit: int) -> list[ReadingStep]:
    """优先项目说明及可用关系，同一问题/文件只占一个展示位置。"""
    # 同一清单的多个命令、同一文件的多个导出一起展示，避免只留下第一项。
    candidates = list(candidates)
    for entry in list(candidates):
        if entry.kind != "interface" or not any(
            item.kind == "source_entry" for item in entry.evidence
        ):
            continue
        for index, step in enumerate(candidates):
            if step.kind == "definition" and any(
                (target.path, target.line) == (step.location.path, step.location.line)
                for target in entry.related
            ):
                candidates[index] = replace(
                    step,
                    goal="entry",
                    reason=step.reason if step.goal == "entry" else entry.reason,
                    evidence=tuple(dict.fromkeys((*step.evidence, *entry.evidence))),
                    related=tuple(dict.fromkeys((*step.related, entry.location)))[:6],
                )
                candidates.remove(entry)
                break
    interfaces: dict[tuple[str, str], list[ReadingStep]] = {}
    pending: list[ReadingStep] = []
    for step in candidates:
        if step.kind == "interface" and step.goal in {"entry", "contract"}:
            interfaces.setdefault((step.goal, step.location.path), []).append(step)
        else:
            pending.append(step)
    for values in interfaces.values():
        values.sort(key=priority)
        first = values[0]
        if len(values) == 1:
            pending.append(first)
            continue
        evidence = tuple(
            dict.fromkeys(item for step in values for item in step.evidence)
        )
        related = tuple(dict.fromkeys(item for step in values for item in step.related))
        names = "；".join(step.summary for step in values[:6])
        if len(values) > 6:
            names += f"；另有 {len(values) - 6} 项，见同一声明文件。"
        pending.append(
            replace(
                first,
                summary=names,
                evidence=evidence[:64],
                related=related[:6],
                learn="核对这些声明及已定位的定义；声明列表本身不解释具体功能。",
            )
        )
    result: list[ReadingStep] = []
    used: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    budgets = {
        "purpose": 1,
        "structure": 1,
        "entry": 2,
        "usage": 3,
        "contract": 2,
        "implementation": 2,
        "document": 1,
        "component": 1,
    }
    for step in sorted(pending, key=priority):
        if step.goal == "maintenance":
            continue
        goal = "purpose" if step.goal == "overview" else step.goal
        if counts[goal] >= budgets.get(goal, 1):
            continue
        key = (
            step.goal + ":" + step.kind,
            step.location.path
            + (f":{step.location.line}" if step.kind == "definition" else ""),
        )
        if key in used:
            continue
        used.add(key)
        counts[goal] += 1
        result.append(step)
        if len(result) >= limit:
            break
    return result
