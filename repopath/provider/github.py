"""GitHub 公开仓库快照 Provider。"""

import io
import json
import os
import stat
import string
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import IncompleteRead
from pathlib import Path, PurePosixPath
from time import sleep
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import OpenerDirector, Request, build_opener

from ..model.repository import (
    GitHubRateLimit,
    Repository,
    RepositorySource,
    RepositorySourceType,
)
from ..model.options import GitHubSnapshotLimits


GITHUB_API_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.5
MAX_SNAPSHOT_FILES = 10_000
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024


class GitHubApiError(RuntimeError):
    """表示 GitHub API 请求或响应无法用于仓库快照。"""


@dataclass(frozen=True)
class HttpResponse:
    """保存 HTTP 传输层返回的状态、头和响应体。"""

    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    """定义 GitHub 客户端所需的最小 HTTP GET 能力。"""

    def get(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        """发送 GET 请求并返回原始 HTTP 响应。"""
        ...


class UrllibHttpTransport:
    """使用可复用的标准库 opener 发送 GitHub API 请求。"""

    def __init__(
        self,
        *,
        attempts: int = MAX_REQUEST_ATTEMPTS,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ) -> None:
        """创建复用连接并带有限重试的 HTTP opener。"""
        self.opener: OpenerDirector = build_opener()
        self.attempts = max(1, attempts)
        self.retry_delay = max(0.0, retry_delay)

    def get(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        """发送请求并将 HTTP 和网络失败统一为客户端错误。"""
        request = Request(url, headers=dict(headers), method="GET")
        last_error: BaseException | None = None
        for attempt in range(self.attempts):
            try:
                with self.opener.open(
                    request, timeout=timeout
                ) as response:
                    return HttpResponse(
                        response.status,
                        dict(response.headers.items()),
                        response.read(),
                    )
            except HTTPError as exc:
                return HttpResponse(
                    exc.code,
                    dict(exc.headers.items()) if exc.headers else {},
                    exc.read(),
                )
            except (
                IncompleteRead,
                URLError,
                TimeoutError,
                OSError,
            ) as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    sleep(self.retry_delay)
        raise GitHubApiError(
            f"GitHub 请求传输中断，已重试 {self.attempts} 次"
        ) from last_error


@dataclass(frozen=True)
class GitHubRepositoryRef:
    """表示经校验的 GitHub 仓库所有者和名称。"""

    owner: str
    name: str

    @classmethod
    def parse(cls, location: str) -> "GitHubRepositoryRef":
        """解析 GitHub 仓库地址并拒绝歧义或非公开域名输入。"""
        candidate = location.strip()
        if not candidate or any(
            character.isspace() or ord(character) < 32
            for character in candidate
        ):
            raise ValueError(
                "GitHub 仓库地址不能为空且不能包含空白或控制字符"
            )
        if "://" not in candidate and not candidate.lower().startswith(
            "github.com/"
        ):
            candidate = f"github.com/{candidate}"
        url = (
            candidate if "://" in candidate else f"https://{candidate}"
        )
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "github.com"
        ):
            raise ValueError(
                "GitHub 仓库地址必须是 https://github.com/所有者/仓库"
            )
        if (
            parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "GitHub 仓库地址不能包含账号、查询参数或片段"
            )
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2:
            raise ValueError("GitHub 仓库地址必须包含所有者和仓库名称")
        owner, name = parts
        if name.endswith(".git"):
            name = name[:-4]
        allowed = set(string.ascii_letters + string.digits + "-_.")
        if (
            not owner
            or not name
            or any(
                character not in allowed
                for item in (owner, name)
                for character in item
            )
        ):
            raise ValueError("GitHub 仓库所有者或名称无效")
        return cls(owner=owner, name=name)

    @property
    def location(self) -> str:
        """返回规范化的 GitHub 仓库网页地址。"""
        return f"https://github.com/{self.owner}/{self.name}"


@dataclass(frozen=True)
class GitHubCommit:
    """保存 GitHub API 返回的固定提交标识。"""

    sha: str


class GitHubApiClient:
    """封装公开 GitHub 仓库快照所需的 REST API 调用。"""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        api_url: str = GITHUB_API_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        token: str | None = None,
    ) -> None:
        """创建带统一传输层、地址、超时和可选 Token 的客户端。"""
        self.transport = transport or UrllibHttpTransport()
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def rate_limit(self) -> GitHubRateLimit:
        """读取当前凭据或 IP 的 GitHub Core API 额度。"""
        payload = self._get_json("/rate_limit")
        resources = _as_object_mapping(payload.get("resources"))
        core = (
            _as_object_mapping(resources.get("core"))
            if resources is not None
            else None
        )
        if core is None:
            raise GitHubApiError("GitHub API 未返回 Core 额度信息")
        limit = _integer_field(core, "limit")
        remaining = _integer_field(core, "remaining")
        reset = _integer_field(core, "reset")
        if (
            limit <= 0
            or remaining < 0
            or remaining > limit
            or reset <= 0
        ):
            raise GitHubApiError(
                "GitHub API 返回了无效的 Core 额度信息"
            )
        return GitHubRateLimit(limit, remaining, reset)

    def repository_default_branch(
        self, repository: GitHubRepositoryRef
    ) -> str:
        """读取公开仓库的默认分支名称。"""
        payload = self._get_json(
            f"/repos/{repository.owner}/{repository.name}"
        )
        branch = payload.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise GitHubApiError("GitHub API 未返回默认分支")
        return branch

    def resolve_commit(
        self, repository: GitHubRepositoryRef, reference: str
    ) -> GitHubCommit:
        """将分支、标签或提交引用固定解析为提交 SHA。"""
        payload = self._get_json(
            f"/repos/{repository.owner}/{repository.name}/commits/"
            f"{quote(reference, safe='')}"
        )
        sha = payload.get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitHubApiError("GitHub API 未返回有效的提交 SHA")
        return GitHubCommit(sha=sha)

    def archive_content(
        self,
        repository: GitHubRepositoryRef,
        sha: str,
        *,
        max_bytes: int = MAX_ARCHIVE_BYTES,
    ) -> bytes:
        """下载固定提交的 zipball，避免逐文件消耗 API 配额。"""
        response = self.transport.get(
            f"{self.api_url}/repos/{repository.owner}/"
            f"{repository.name}/"
            f"zipball/{quote(sha, safe='')}",
            self._headers(),
            self.timeout,
        )
        self._raise_for_error(response)
        if not response.body:
            raise GitHubApiError("GitHub API 返回了空的仓库归档")
        if len(response.body) > max_bytes:
            raise GitHubApiError("GitHub 仓库归档超过下载大小限制")
        return response.body

    def _get_json(self, path: str) -> dict[str, object]:
        """请求 JSON API 并转换常见 HTTP 失败为中文错误。"""
        response = self.transport.get(
            f"{self.api_url}{path}",
            self._headers(),
            self.timeout,
        )
        self._raise_for_error(response)
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubApiError(
                "GitHub API 返回了无效的 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise GitHubApiError("GitHub API 返回了无效的对象响应")
        return cast(dict[str, object], payload)

    def _headers(self) -> dict[str, str]:
        """构造 GitHub API 与归档下载共用的请求头。"""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "RepoPath/0.7.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _raise_for_error(self, response: HttpResponse) -> None:
        """将 HTTP 失败转换为带额度提示的 GitHub API 错误。"""
        if response.status < 200 or response.status >= 300:
            message = _response_message(response.body)
            if response.status == 404:
                raise GitHubApiError(
                    "GitHub 仓库、分支或提交不存在，或仓库不是公开仓库"
                )
            if (
                response.status == 403
                and response.headers.get("X-RateLimit-Remaining") == "0"
            ):
                raise GitHubApiError(
                    "GitHub API 请求额度已用尽，请稍后重试"
                )
            raise GitHubApiError(
                f"GitHub API 请求失败（HTTP {response.status}）：{message}"
            )


class GitHubSnapshot:
    """在临时目录中物化一个固定 GitHub 提交供现有 Analyzer 使用。"""

    def __init__(
        self,
        source: RepositorySource,
        client: GitHubApiClient | None = None,
        limits: GitHubSnapshotLimits | None = None,
    ) -> None:
        """保存待读取的 GitHub 来源和 API 客户端。"""
        if source.type is not RepositorySourceType.GITHUB:
            raise ValueError("GitHub 快照只支持 GitHub 仓库来源")
        self.source = source
        self.client = client or GitHubApiClient()
        self.limits = limits or GitHubSnapshotLimits()
        self.limits.validate()
        self._temporary_directory: (
            tempfile.TemporaryDirectory[str] | None
        ) = None
        self.rate_limit: GitHubRateLimit | None = None

    def __enter__(self) -> "GitHubSnapshot":
        """下载固定提交的文件并创建临时本地仓库。"""
        repository_ref = GitHubRepositoryRef.parse(self.source.location)
        self.rate_limit = self.client.rate_limit()
        reference = (self.source.reference or "").strip()
        if reference and any(
            character.isspace() or ord(character) < 32
            for character in reference
        ):
            raise ValueError("GitHub 引用不能包含空白或控制字符")
        reference = reference or self.client.repository_default_branch(
            repository_ref
        )
        commit = self.client.resolve_commit(repository_ref, reference)
        archive_content = self.client.archive_content(
            repository_ref,
            commit.sha,
            max_bytes=self.limits.archive_max_bytes,
        )
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="repopath-github-"
        )
        root = Path(self._temporary_directory.name)
        try:
            self._extract_archive(
                root, archive_content, limits=self.limits
            )
        except Exception:
            self._temporary_directory.cleanup()
            self._temporary_directory = None
            raise
        self.repository = Repository(
            root=root.resolve(), display_name=repository_ref.name
        )
        self.resolved_source = RepositorySource.github(
            repository_ref.location, commit.sha
        )
        return self

    def __exit__(
        self, exc_type: object, exc_value: object, traceback: object
    ) -> None:
        """清理本次分析使用的临时仓库目录。"""
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    @staticmethod
    def _extract_archive(
        root: Path,
        archive_content: bytes,
        *,
        limits: GitHubSnapshotLimits | None = None,
    ) -> None:
        """校验 zipball 路径和规模后安全写入临时目录。"""
        try:
            with zipfile.ZipFile(
                io.BytesIO(archive_content)
            ) as archive:
                files = _archive_files(archive, limits=limits)
                for entry, path in files:
                    destination = root / PurePosixPath(path)
                    destination.parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    destination.write_bytes(archive.read(entry))
        except GitHubApiError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise GitHubApiError(
                "GitHub 仓库归档无效或无法解压"
            ) from exc


def _is_safe_repository_path(path: str) -> bool:
    """判断归档文件路径能否安全写入临时目录。"""
    candidate = PurePosixPath(path)
    return (
        bool(path)
        and not candidate.is_absolute()
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in candidate.parts)
    )


def _archive_files(
    archive: zipfile.ZipFile,
    *,
    limits: GitHubSnapshotLimits | None = None,
) -> list[tuple[zipfile.ZipInfo, str]]:
    """筛选安全的归档文件并校验解压后的资源上限。"""
    root_name: str | None = None
    total_size = 0
    files: list[tuple[zipfile.ZipInfo, str]] = []
    paths: set[str] = set()
    active_limits = limits or GitHubSnapshotLimits()
    active_limits.validate()
    for entry in archive.infolist():
        if entry.is_dir() or _is_symbolic_link(entry):
            continue
        parts = PurePosixPath(entry.filename).parts
        if len(parts) < 2:
            raise GitHubApiError("GitHub 仓库归档缺少顶层目录")
        if root_name is None:
            root_name = parts[0]
        if parts[0] != root_name:
            raise GitHubApiError("GitHub 仓库归档包含多个顶层目录")
        path = PurePosixPath(*parts[1:]).as_posix()
        if not _is_safe_repository_path(path):
            raise GitHubApiError("GitHub 仓库归档包含不安全的文件路径")
        if entry.file_size > active_limits.file_max_bytes:
            raise GitHubApiError(
                f"文件 {path} 超过远程快照单文件大小限制"
            )
        if path in paths:
            raise GitHubApiError("GitHub 仓库归档包含重复文件路径")
        paths.add(path)
        files.append((entry, path))
        total_size += entry.file_size
        if len(files) > active_limits.file_limit:
            raise GitHubApiError("仓库文件数超过远程快照限制")
        if total_size > active_limits.content_max_bytes:
            raise GitHubApiError("仓库文件总大小超过远程快照限制")
    return files


def _is_symbolic_link(entry: zipfile.ZipInfo) -> bool:
    """判断 zip 条目是否表示 Unix 符号链接。"""
    mode = entry.external_attr >> 16
    return stat.S_ISLNK(mode)


def _response_message(body: bytes) -> str:
    """从失败响应中提取简短的 GitHub 错误信息。"""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "未提供错误详情"
    payload_mapping = _as_object_mapping(payload)
    message = (
        payload_mapping.get("message")
        if payload_mapping is not None
        else None
    )
    return (
        message
        if isinstance(message, str) and message
        else "未提供错误详情"
    )


def _as_object_mapping(value: object) -> dict[str, object] | None:
    """将 JSON 对象安全窄化为字符串键的映射。"""
    return (
        cast(dict[str, object], value)
        if isinstance(value, dict)
        else None
    )


def _integer_field(payload: Mapping[str, object], name: str) -> int:
    """读取 GitHub JSON 对象中的非布尔整数值。"""
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise GitHubApiError(f"GitHub API 未返回有效的额度字段：{name}")
    return value
