"""仓库分析配置模型。"""

from dataclasses import dataclass, replace


VALID_PROFILES = {"fast", "standard", "deep", "custom"}
VALID_GIT_PERIODS = {"all", "30", "90"}
VALID_CPP_BACKENDS = {"basic", "libclang"}


@dataclass(frozen=True)
class GitHubSnapshotLimits:
    """保存 GitHub 快照下载和解压的资源上限。"""

    archive_max_bytes: int = 100 * 1024 * 1024
    file_limit: int = 10_000
    content_max_bytes: int = 100 * 1024 * 1024
    file_max_bytes: int = 10 * 1024 * 1024

    def validate(self) -> None:
        """校验 GitHub 快照资源上限均为正数。"""
        for value in (
            self.archive_max_bytes,
            self.file_limit,
            self.content_max_bytes,
            self.file_max_bytes,
        ):
            if value <= 0:
                raise ValueError("GitHub 快照资源上限必须大于 0")


@dataclass(frozen=True)
class AnalysisOptions:
    """保存 CLI、配置文件和 UI 共用的分析选项。"""

    profile: str = "deep"
    python_enabled: bool = True
    cpp_enabled: bool = True
    cpp_backend: str = "basic"
    cpp_compile_commands: str | None = None
    git_enabled: bool = True
    dependencies_enabled: bool = True
    insights_enabled: bool = True
    max_file_size: int | None = 2 * 1024 * 1024
    follow_symlinks: bool = False
    result_limit: int = 50
    reading_limit: int = 10
    include_file_list: bool = False
    git_period: str = "all"
    excluded_patterns: tuple[str, ...] = ()
    github_archive_max_bytes: int = 100 * 1024 * 1024
    github_file_limit: int = 10_000
    github_content_max_bytes: int = 100 * 1024 * 1024
    github_file_max_bytes: int = 10 * 1024 * 1024

    @classmethod
    def for_profile(cls, profile: str) -> "AnalysisOptions":
        """根据预设模式创建分析选项。"""
        if profile not in VALID_PROFILES:
            raise ValueError(f"未知分析模式：{profile}")
        if profile == "fast":
            return cls(
                profile=profile,
                python_enabled=False,
                cpp_enabled=False,
                git_enabled=False,
                dependencies_enabled=False,
                insights_enabled=False,
            )
        if profile == "standard":
            return cls(
                profile=profile,
                dependencies_enabled=False,
                insights_enabled=False,
            )
        return cls(profile=profile)

    def with_overrides(self, **values: object) -> "AnalysisOptions":
        """返回应用非空覆盖值后的分析选项。"""
        filtered = {
            key: value
            for key, value in values.items()
            if value is not None
        }
        options = replace(self, **filtered)
        options.validate()
        return options

    def validate(self) -> None:
        """校验分析选项的取值和依赖关系。"""
        if self.profile not in VALID_PROFILES:
            raise ValueError(f"未知分析模式：{self.profile}")
        if self.git_period not in VALID_GIT_PERIODS:
            raise ValueError("Git 时间范围必须是 all、30 或 90")
        if self.cpp_backend not in VALID_CPP_BACKENDS:
            raise ValueError("C++ 分析方式必须是 basic 或 libclang")
        if self.cpp_compile_commands is not None and (
            not isinstance(self.cpp_compile_commands, str)
            or not self.cpp_compile_commands.strip()
        ):
            raise ValueError("C++ 编译配置路径必须是非空字符串")
        if self.max_file_size is not None and self.max_file_size <= 0:
            raise ValueError("最大文件大小必须大于 0")
        if self.result_limit <= 0:
            raise ValueError("报告列表最大数量必须大于 0")
        if self.reading_limit <= 0:
            raise ValueError("阅读和评分列表最大数量必须大于 0")
        if self.dependencies_enabled and not (
            self.python_enabled or self.cpp_enabled
        ):
            raise ValueError(
                "依赖分析至少需要启用 Python 或 C++ Analyzer"
            )
        if self.insights_enabled and not self.dependencies_enabled:
            raise ValueError("阅读洞察需要启用依赖分析")
        self.github_snapshot_limits.validate()

    @property
    def github_snapshot_limits(self) -> GitHubSnapshotLimits:
        """返回当前配置对应的 GitHub 快照资源上限。"""
        return GitHubSnapshotLimits(
            archive_max_bytes=self.github_archive_max_bytes,
            file_limit=self.github_file_limit,
            content_max_bytes=self.github_content_max_bytes,
            file_max_bytes=self.github_file_max_bytes,
        )

    def analyzer_enabled(self, name: str) -> bool:
        """判断指定 Analyzer 是否应在当前配置下运行。"""
        switches = {
            "python": self.python_enabled,
            "cpp": self.cpp_enabled,
            "git": self.git_enabled,
            "dependencies": self.dependencies_enabled,
            "insights": self.insights_enabled,
        }
        return switches.get(name, True)
