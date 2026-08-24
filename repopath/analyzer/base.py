"""Analyzer 基础协议。"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..model.result import AnalysisResult, AnalysisState

if TYPE_CHECKING:
    from ..core.context import AnalysisContext


class Analyzer(ABC):
    """定义可被 Core Pipeline 调度的分析器接口。"""

    name = "analyzer"

    @abstractmethod
    def analyze(self, context: "AnalysisContext", state: AnalysisState) -> AnalysisResult:
        """基于上下文和已有结果执行一次分析。"""
        raise NotImplementedError
