"""Analyzer 通用结果和 Pipeline 状态模型。"""

from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """包装一个 Analyzer 的数据、警告和错误。"""

    name: str
    data: object | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def successful(self) -> bool:
        """判断 Analyzer 是否没有产生错误。"""
        return not self.errors


@dataclass
class AnalysisState:
    """保存 Pipeline 中各 Analyzer 的执行结果。"""

    results: dict[str, AnalysisResult] = field(default_factory=dict)

    def add(self, result: AnalysisResult) -> None:
        """保存一个 Analyzer 结果并按名称索引。"""
        self.results[result.name] = result

    def get_data(self, name: str, default: object = None) -> object:
        """读取指定 Analyzer 的数据，不存在时返回默认值。"""
        result = self.results.get(name)
        return result.data if result is not None and result.data is not None else default

    @property
    def warnings(self) -> list[str]:
        """汇总所有 Analyzer 的警告信息。"""
        return [warning for result in self.results.values() for warning in result.warnings]

    @property
    def errors(self) -> list[str]:
        """汇总所有 Analyzer 的错误信息。"""
        return [error for result in self.results.values() for error in result.errors]
