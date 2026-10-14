"""CLI 报告与 UI 共用的阅读指南展示约定。"""

from ..model.reading import ReadingLocation, ReadingStep
from ..model.report import RepositoryReport
from ..model.result import AnalyzerName, AnalyzerStatus

READING_BOUNDARY = (
    "文档是作者说明；候选关系未经运行验证，不代表重要性或执行顺序。片段可能不完整。"
)
CONFIDENCE_LABELS = {
    "observed": "直接观察",
    "documented": "文档描述",
    "candidate": "候选关联",
}
KIND_LABELS = {
    "document": "文档片段",
    "interface": "接口声明",
    "definition": "定义位置",
    "usage": "使用位置",
}
EVIDENCE_LABELS = {
    "document_section": "文档章节",
    "document_link": "文档链接",
    "manifest_entry": "清单声明",
    "python_docstring": "Python 说明文字",
    "python_export": "Python 导出声明",
    "python_import": "Python 导入引用",
    "python_call_expression": "Python 调用表达式",
    "cpp_symbol": "C++ 符号位置",
    "cpp_include": "C++ 头文件引用",
}
GAP_LABELS = {
    "outside_root": "范围外路径",
    "outside_link": "范围外链接",
    "unresolved_link": "未定位链接",
    "unresolved_fragment": "未定位片段",
    "read_budget": "读取上限",
    "fact_budget": "证据上限",
    "candidate_budget": "候选上限",
    "relation_budget": "关联检查上限",
    "related_limit": "关联位置上限",
    "gap_limit": "缺口记录上限",
    "selection_limit": "阅读步骤上限",
    "no_evidence": "缺少证据",
    "unreadable": "读取失败",
    "invalid_manifest": "清单解析失败",
    "unsupported_entry": "暂不支持的入口声明",
    "ambiguous_entry": "入口有多个候选",
    "unresolved_entry": "未定位入口",
    "invalid_python": "Python 解析失败",
    "dynamic_export": "动态导出",
    "unresolved_export": "未定位导出",
    "ambiguous_symbol": "符号有多个候选",
    "python_unavailable": "Python 分析不可用",
    "cpp_unavailable": "C++ 分析不可用",
    "incomplete_cpp": "C++ 分析范围有限",
    "ambiguous_cpp_symbol": "C++ 符号有多个候选",
}
READING_STEP_LIMIT = 100


def format_location(location: ReadingLocation) -> str:
    """保留仓库相对位置与完整范围，便于从报告回到证据。"""
    position = f"{location.path}:{location.line}"
    if location.end_line is not None and location.end_line != location.line:
        position += f"-{location.end_line}"
    return position


def reading_detail_limit(report: RepositoryReport) -> int:
    """限制单处辅助列表长度，模型保留的全部条目仍可在 JSON 查看。"""
    return min(report.options.result_limit, 50)


def unique_preview_locations(
    step: ReadingStep, detail_limit: int,
) -> list[ReadingLocation]:
    """单步内相同位置的相同片段只展示一次，保留不同来源或内容。"""
    locations = [
        step.location,
        *(evidence.location for evidence in step.evidence[:detail_limit]),
        *step.related[:detail_limit],
    ]
    return list(dict.fromkeys(location for location in locations if location.excerpt))


def reading_state(report: RepositoryReport) -> str:
    """说明实际执行结果，区分没有运行、失败与证据不足。"""
    result = report.analyzer_result(AnalyzerName.READING)
    if result.status == AnalyzerStatus.NOT_RUN:
        return "阅读指南未运行。"
    if result.status == AnalyzerStatus.FAILED:
        return "阅读指南分析失败；仅保留部分结果。"
    if not result.successful:
        return "阅读指南有错误；仅保留部分结果。"
    guide = report.reading_guide
    if not guide.steps:
        return "证据不足以生成阅读步骤。"
    if guide.gaps or guide.truncated:
        return "部分阅读指南：存在分析缺口或截断。"
    return "已生成阅读指南。"
