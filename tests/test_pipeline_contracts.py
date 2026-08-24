"""Provider 契约和 Pipeline 进度测试。"""

from collections.abc import Iterator
from pathlib import Path

from repopath.analyzer.file_analyzer import FileAnalyzer
from repopath.core.context import AnalysisContext
from repopath.core.control import AnalysisCancelled, CancellationToken
from repopath.core.pipeline import Pipeline
from repopath.model.options import AnalysisOptions
from repopath.model.repository import Repository, RepositorySource
from repopath.model.result import AnalysisProgress
from repopath.provider.git import GitProvider
import pytest


class FakeFileProvider:
    """提供测试使用的内存式文件列表。"""

    def __init__(self, path: Path) -> None:
        """保存测试文件路径。"""
        self.path = path

    def iter_files(
        self, excluded_paths: set[Path] | None = None
    ) -> Iterator[Path]:
        """返回唯一的测试文件。"""
        yield self.path

    def read_text(self, path: Path) -> str | None:
        """返回固定 Python 源码。"""
        return "value = 1\n"


def test_pipeline_accepts_provider_protocol_and_reports_progress(
    tmp_path: Path,
) -> None:
    """验证 Pipeline 使用文件 Provider 协议并发送阶段进度。"""
    path = tmp_path / "sample.py"
    repository = Repository.from_path(tmp_path)
    context = AnalysisContext(
        repository=repository,
        source=RepositorySource.local(tmp_path),
        filesystem=FakeFileProvider(path),
        git=GitProvider(repository),
        options=AnalysisOptions.for_profile("fast"),
    )
    events: list[AnalysisProgress] = []

    state = Pipeline([FileAnalyzer()]).run(context, events.append)

    assert len(state.artifacts.files) == 1
    assert [event.status for event in events] == ["running", "finished"]
    assert events[-1].percent == 100
    assert state.durations["files"] >= 0


def test_pipeline_propagates_cancellation_before_analyzer(
    tmp_path: Path,
) -> None:
    """验证 Pipeline 不会把取消请求转换成 Analyzer 局部错误。"""
    path = tmp_path / "sample.py"
    repository = Repository.from_path(tmp_path)
    cancellation = CancellationToken()
    cancellation.cancel()
    context = AnalysisContext(
        repository=repository,
        source=RepositorySource.local(tmp_path),
        filesystem=FakeFileProvider(path),
        git=GitProvider(repository),
        options=AnalysisOptions.for_profile("fast"),
        cancellation=cancellation,
    )

    with pytest.raises(AnalysisCancelled):
        Pipeline([FileAnalyzer()]).run(context)
