"""C++ 语义分析选项与命令行状态测试。"""

import json
from pathlib import Path

import pytest

from repopath.core.config import AnalysisConfigError, load_analysis_options
from repopath.interface import cli
from repopath.model.options import AnalysisOptions
from repopath.model.report import RepositoryReport
from repopath.model.repository import Repository
from repopath.model.result import AnalysisResult, AnalyzerName, AnalyzerStatus


def test_cpp_cli_overrides_config_without_changing_profile(
    tmp_path: Path,
) -> None:
    """验证选择语义分析不会改变其他分析开关，CLI 可覆盖配置。"""
    (tmp_path / ".repopath.toml").write_text(
        '[scan]\nprofile = "standard"\n'
        '[cpp]\nbackend = "libclang"\n'
        'compile_commands = "build/compile_commands.json"\n',
        encoding="utf-8",
    )
    configured = load_analysis_options(tmp_path)
    assert configured.cpp_backend == "libclang"
    assert configured.cpp_compile_commands == "build/compile_commands.json"
    args = cli.build_parser().parse_args([
        str(tmp_path), "--cpp-backend", "basic",
        "--compile-commands", "other build/compile_commands.json",
    ])

    options = cli._resolve_options(tmp_path, args)

    assert options.cpp_backend == "basic"
    assert options.cpp_compile_commands == "other build/compile_commands.json"
    assert options.profile == "standard"
    assert options.dependencies_enabled is False
    assert options.cpp_enabled is True


@pytest.mark.parametrize("setting", [
    'backend = "unknown"',
    'backend = true',
    'compile_commands = 1',
    'compile_commands = ""',
])
def test_cpp_config_rejects_invalid_values(
    tmp_path: Path, setting: str,
) -> None:
    """验证无效后端和路径会在配置阶段报错。"""
    (tmp_path / ".repopath.toml").write_text(
        f"[cpp]\n{setting}\n", encoding="utf-8",
    )

    with pytest.raises(AnalysisConfigError):
        load_analysis_options(tmp_path)


@pytest.mark.parametrize("status, semantic_status, expected_exit", [
    (AnalyzerStatus.FAILED, "failed", 1),
    (AnalyzerStatus.COMPLETED, "partial", 0),
])
def test_cpp_cli_keeps_report_and_exposes_semantic_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: AnalyzerStatus,
    semantic_status: str,
    expected_exit: int,
) -> None:
    """验证执行失败返回非零，部分分析保留报告并明确提示。"""
    def analyze(*args: object, **kwargs: object) -> RepositoryReport:
        """返回独立于本机 libclang 安装的状态样例。"""
        options = kwargs["options"]
        assert isinstance(options, AnalysisOptions)
        report = RepositoryReport(
            repository=Repository.from_path(tmp_path), options=options,
        )
        report.cpp.backend = "libclang"
        report.cpp.analysis_level = "semantic"
        report.cpp.semantic_status = semantic_status
        report.cpp.semantic_reason = "缺少头文件或分析库"
        report.analyzer_results[AnalyzerName.CPP] = AnalysisResult(
            name=AnalyzerName.CPP, status=status,
            reason="缺少头文件或分析库" if expected_exit else None,
        )
        return report

    monkeypatch.setattr(cli, "analyze_repository", analyze)

    result = cli.main([
        str(tmp_path), "--cpp-backend", "libclang", "--format", "json",
    ])

    assert result == expected_exit
    output = tmp_path / "REPOPATH_REPORT.json"
    assert json.loads(output.read_text(encoding="utf-8"))["cpp"]["status"] == status
    captured = capsys.readouterr()
    if expected_exit:
        assert "C++ 语义分析未完成" in captured.err
    else:
        assert "C++ 语义分析仅覆盖部分内容" in captured.out
