"""验证打包准备显式携带同源运行库，不能借助宿主系统补库。"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts import prepare_cpp_package as preparation


def runtime_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    """构造各平台均可运行的 PE 依赖样例。"""
    source = tmp_path / "redist"
    python_directory = tmp_path / "python"
    source.mkdir()
    python_directory.mkdir()
    library = tmp_path / "libclang.dll"
    library.touch()
    python_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    (python_directory / python_name).touch()
    imports = {
        "libclang.dll": {"msvcp140.dll", "kernel32.dll"},
        python_name: {"vcruntime140_1.dll"},
        "msvcp140.dll": {"vcruntime140.dll"},
        "vcruntime140.dll": {"api-ms-win-crt-runtime-l1-1-0.dll"},
        "vcruntime140_1.dll": {"vcruntime140.dll"},
    }
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        (source / name).write_bytes(name.encode())

    def read_imports(path: Path) -> set[str]:
        return imports[path.name]

    def read_info(path: Path) -> tuple[int, tuple[int, ...]]:
        return 0x8664, (14, 44, 1, 0)

    monkeypatch.setattr(preparation, "pe_import_names", read_imports)
    monkeypatch.setattr(preparation, "binary_info", read_info)
    return source, library, python_directory


def test_runtime_collection_includes_python_and_transitive_crt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一份 redist 同时满足 Python、libclang 及其间接运行库依赖。"""
    source, library, python_directory = runtime_fixture(tmp_path, monkeypatch)
    (source / "concrt140.dll").touch()

    files = preparation.collect_windows_runtime(source, library, python_directory)

    assert set(files) == {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
    assert all(file.parent == source for file in files.values())


def test_missing_runtime_does_not_fall_back_to_python_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开发机的同名 DLL 不能掩盖可再分发来源缺失。"""
    source, library, python_directory = runtime_fixture(tmp_path, monkeypatch)
    (source / "vcruntime140.dll").unlink()
    (python_directory / "vcruntime140.dll").touch()

    with pytest.raises(RuntimeError, match="缺少运行库 vcruntime140.dll"):
        preparation.collect_windows_runtime(source, library, python_directory)


def test_old_redist_cannot_be_silently_replaced_by_python_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nuitka 会优先选择新版本，准备阶段需拒绝更旧的显式来源。"""
    source, library, python_directory = runtime_fixture(tmp_path, monkeypatch)
    (python_directory / "vcruntime140.dll").touch()

    def read_info(path: Path) -> tuple[int, tuple[int, ...]]:
        return 0x8664, (14, 45 if path.parent == python_directory else 44, 1, 0)

    monkeypatch.setattr(preparation, "binary_info", read_info)

    with pytest.raises(RuntimeError, match="低于或无法对比"):
        preparation.collect_windows_runtime(source, library, python_directory)


def test_runtime_collection_rejects_system_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System32 不是构建脚本支持的可再分发文件来源。"""
    source, library, python_directory = runtime_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    with pytest.raises(RuntimeError, match="Windows 系统目录"):
        preparation.collect_windows_runtime(source, library, python_directory)


def test_runtime_collection_rejects_ambiguous_redist_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多个版本不能拼成一个看似完整的运行库集合。"""
    source, library, python_directory = runtime_fixture(tmp_path, monkeypatch)
    older = source / "older"
    older.mkdir()
    (older / "msvcp140.dll").write_bytes(b"different runtime")

    with pytest.raises(RuntimeError, match="多个不同的 x64 msvcp140.dll"):
        preparation.collect_windows_runtime(source, library, python_directory)


def test_runtime_manifest_preserves_hashes_without_private_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """随包清单可核验实际 DLL，且许可证目录不携带作为数据文件的 DLL。"""
    source, library, python_directory = runtime_fixture(tmp_path, monkeypatch)
    files = preparation.collect_windows_runtime(source, library, python_directory)
    data = tmp_path / "licenses"
    runtime = tmp_path / "runtime"
    config = tmp_path / "runtime.nuitka-package.config.yml"

    preparation.write_runtime_package(files, runtime, config, data, "explicit-directory")

    manifest = json.loads((data / "windows-runtime.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "explicit-directory"
    assert str(tmp_path) not in json.dumps(manifest)
    for item in manifest["files"]:
        expected = hashlib.sha256(files[item["name"]].read_bytes()).hexdigest()
        assert item["sha256"] == expected
        assert item["version"] == [14, 44, 1, 0]
        assert (runtime / Path(item["name"]).stem / item["name"]).is_file()
    assert not list(data.rglob("*.dll"))
    assert "  dlls:" in config.read_text(encoding="utf-8")


def test_runtime_discovery_prefers_newest_visual_studio_redist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自动选择只在 Visual Studio 的 Redist 目录中比较版本。"""
    directories: list[Path] = []
    for version in ("14.40", "14.44"):
        directory = tmp_path / (
            f"Microsoft Visual Studio/2022/Community/VC/Redist/MSVC/{version}"
            "/x64/Microsoft.VC143.CRT"
        )
        directory.mkdir(parents=True)
        (directory / "msvcp140.dll").touch()
        directories.append(directory)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("VCToolsRedistDir", raising=False)

    def read_info(path: Path) -> tuple[int, tuple[int, ...]]:
        return 0x8664, (14, 44 if path.parent == directories[1] else 40, 1, 0)

    monkeypatch.setattr(preparation, "binary_info", read_info)

    assert preparation.discover_runtime_directory() == directories[1]
