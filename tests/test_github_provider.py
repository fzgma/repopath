"""GitHub 公开仓库快照测试。"""

import io
import json
import zipfile
from collections.abc import Mapping
from http.client import IncompleteRead
from typing import Any, cast

import pytest

from repopath.core.service import analyze_repository
from repopath.model.options import AnalysisOptions
from repopath.model.options import GitHubSnapshotLimits
from repopath.model.repository import RepositorySource
from repopath.provider.github import (
    GitHubApiClient,
    GitHubApiError,
    GitHubRepositoryRef,
    GitHubSnapshot,
    HttpResponse,
    UrllibHttpTransport,
)
from repopath.renderer.json import JsonRenderer
from repopath.renderer.markdown import MarkdownRenderer


API_ROOT = "https://api.github.com"
TEST_API_URL = "https://api.github.com/repos/example/demo"


class FakeTransport:
    """按 URL 返回预设 GitHub API 响应。"""

    def __init__(self, payloads: Mapping[str, HttpResponse]) -> None:
        """保存 URL 对应的固定 HTTP 响应。"""
        self.payloads = payloads
        self.urls: list[str] = []
        self.headers: list[Mapping[str, str]] = []

    def get(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        """记录请求并返回匹配的 JSON 响应。"""
        self.urls.append(url)
        self.headers.append(headers)
        return self.payloads[url]


class _ReadFailureResponse:
    """首次读取时模拟 GitHub 快照连接提前关闭。"""

    status = 200
    headers: Mapping[str, str] = {}

    def __enter__(self) -> "_ReadFailureResponse":
        """返回可作为响应上下文使用的自身。"""
        return self

    def __exit__(
        self, exc_type: object, exc_value: object, traceback: object
    ) -> None:
        """接受响应上下文退出。"""

    def read(self) -> bytes:
        """抛出带部分内容的标准库不完整读取异常。"""
        raise IncompleteRead(b"partial", 10)


class _SuccessResponse:
    """提供一次成功读取所需的最小 HTTP 响应接口。"""

    status = 200
    headers: Mapping[str, str] = {}

    def __enter__(self) -> "_SuccessResponse":
        """返回可作为响应上下文使用的自身。"""
        return self

    def __exit__(
        self, exc_type: object, exc_value: object, traceback: object
    ) -> None:
        """接受响应上下文退出。"""

    def read(self) -> bytes:
        """返回重试后成功读取到的归档内容。"""
        return b"complete"


class _RetryingOpener:
    """按顺序返回失败和成功响应的 opener 替身。"""

    def __init__(self) -> None:
        """初始化两次预期请求的响应序列。"""
        self.responses: list[
            _ReadFailureResponse | _SuccessResponse
        ] = [
            _ReadFailureResponse(),
            _SuccessResponse(),
        ]
        self.calls = 0

    def open(
        self, request: object, timeout: float
    ) -> _ReadFailureResponse | _SuccessResponse:
        """返回下一次预设响应并记录调用次数。"""
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _json_response(payload: object) -> HttpResponse:
    """将 JSON 对象编码为成功的 HTTP 响应。"""
    return HttpResponse(200, {}, json.dumps(payload).encode("utf-8"))


def _zip_response(files: Mapping[str, bytes]) -> HttpResponse:
    """创建带 GitHub 顶层目录的测试 zipball 响应。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(f"example-demo-commit/{path}", content)
    return HttpResponse(200, {}, buffer.getvalue())


def _client(
    files: Mapping[str, bytes] | None = None,
) -> tuple[GitHubApiClient, FakeTransport]:
    """创建包含单个 Python 文件的 GitHub API 测试客户端。"""
    api = TEST_API_URL
    transport = FakeTransport(
        {
            f"{API_ROOT}/rate_limit": _json_response(
                {
                    "resources": {
                        "core": {
                            "limit": 60,
                            "remaining": 58,
                            "reset": 1_787_580_330,
                        }
                    }
                }
            ),
            api: _json_response({"default_branch": "main"}),
            f"{api}/commits/main": _json_response(
                {"sha": "commit-sha"}
            ),
            f"{api}/zipball/commit-sha": _zip_response(
                files or {"src/main.py": b'print("hello")\n'}
            ),
        }
    )
    return GitHubApiClient(transport), transport


def test_github_repository_ref_accepts_canonical_web_address() -> None:
    """验证 GitHub 网页地址会规范化为所有者和仓库名称。"""
    reference = GitHubRepositoryRef.parse("github.com/example/demo.git")

    assert reference.owner == "example"
    assert reference.name == "demo"
    assert reference.location == "https://github.com/example/demo"


def test_github_repository_ref_accepts_owner_repository_shorthand() -> (
    None
):
    """验证所有者和仓库的简写会规范化为 GitHub 网页地址。"""
    reference = GitHubRepositoryRef.parse("fzgma/repopath")

    assert reference.location == "https://github.com/fzgma/repopath"


def test_github_snapshot_materializes_fixed_commit_and_cleans_up() -> (
    None
):
    """验证快照将 Blob 写入临时目录并在退出后清理。"""
    client, transport = _client()
    with GitHubSnapshot(
        RepositorySource.github("github.com/example/demo"), client
    ) as snapshot:
        root = snapshot.repository.root
        assert snapshot.resolved_source.reference == "commit-sha"
        assert snapshot.repository.name == "demo"
        assert (root / "src" / "main.py").read_text(
            encoding="utf-8"
        ) == 'print("hello")\n'
        assert transport.urls == [
            f"{API_ROOT}/rate_limit",
            TEST_API_URL,
            f"{TEST_API_URL}/commits/main",
            f"{TEST_API_URL}/zipball/commit-sha",
        ]
    assert not root.exists()


def test_github_snapshot_with_reference_avoids_repository_lookup() -> (
    None
):
    """验证显式引用只请求提交解析和归档下载。"""
    client, transport = _client()

    with GitHubSnapshot(
        RepositorySource.github("github.com/example/demo", "main"),
        client,
    ):
        pass

    assert transport.urls == [
        f"{API_ROOT}/rate_limit",
        f"{TEST_API_URL}/commits/main",
        f"{TEST_API_URL}/zipball/commit-sha",
    ]


def test_github_service_reuses_static_pipeline_and_degrades_git() -> (
    None
):
    """验证远程快照保留静态分析并明确标记 Git 历史不可用。"""
    report = analyze_repository(
        RepositorySource.github("https://github.com/example/demo"),
        options=AnalysisOptions.for_profile("standard"),
        github_client=_client()[0],
    )

    assert report.repository.name == "demo"
    assert report.source is not None
    assert report.source.reference == "commit-sha"
    assert report.github_rate_limit is not None
    assert report.github_rate_limit.limit == 60
    assert report.github_rate_limit.remaining == 58
    assert [
        report.repository.relative_path(item.path)
        for item in report.files
    ] == ["src/main.py"]
    assert report.git.available is False
    assert "GitHub 公开仓库快照不提供 Git 演进统计" in report.warnings
    assert not report.repository.root.exists()
    assert "固定提交：`commit-sha`" in MarkdownRenderer().render(report)
    assert "GitHub API 限额：58 / 60" in MarkdownRenderer().render(
        report
    )
    assert (
        JsonRenderer().render(report).find('"github_api_rate_limit"')
        > 0
    )


def test_github_snapshot_rejects_unsafe_archive_path() -> None:
    """验证远程归档中的路径穿越会阻止快照写入。"""
    client, _ = _client({"../outside.py": b"x"})

    with pytest.raises(GitHubApiError, match="不安全"):
        with GitHubSnapshot(
            RepositorySource.github("github.com/example/demo"), client
        ):
            pass


def test_github_snapshot_uses_configurable_archive_limits() -> None:
    """验证 GitHub 快照使用调用方提供的归档大小上限。"""
    client, _ = _client({"src/main.py": b"x" * 32})
    limits = GitHubSnapshotLimits(archive_max_bytes=1)

    with pytest.raises(GitHubApiError, match="归档超过下载大小限制"):
        with GitHubSnapshot(
            RepositorySource.github("github.com/example/demo"),
            client,
            limits=limits,
        ):
            pass


def test_github_client_sends_optional_token_header() -> None:
    """验证显式 Token 会作为 GitHub Bearer 认证请求头发送。"""
    client, transport = _client()
    client.token = "test-token"

    assert (
        client.repository_default_branch(
            GitHubRepositoryRef("example", "demo")
        )
        == "main"
    )

    assert transport.headers[0]["Authorization"] == "Bearer test-token"


def test_urllib_transport_retries_an_incomplete_response() -> None:
    """验证 zipball 下载中断后会重新请求并返回完整响应。"""
    transport = UrllibHttpTransport(retry_delay=0)
    opener = _RetryingOpener()
    transport.opener = cast(Any, opener)

    response = transport.get("https://example.test/archive", {}, 1)

    assert response.body == b"complete"
    assert opener.calls == 2
