"""打包验收不能被开发机已有运行库或旧的 onefile 负载掩盖。"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import check_cpp_semantics as smoke


def test_runtime_manifest_rejects_old_dll_with_the_same_name(
    tmp_path: Path,
) -> None:
    """文件名齐全仍可能混入旧运行库，验收必须核对实际文件内容。"""
    names = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
    files: list[dict[str, str]] = []
    for name in names:
        content = name.encode("ascii")
        (tmp_path / name).write_bytes(content)
        files.append({
            "name": name, "sha256": hashlib.sha256(content).hexdigest(),
        })
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    (licenses / "windows-runtime.json").write_text(
        json.dumps({"source": "explicit-directory", "files": files}),
        encoding="utf-8",
    )
    smoke.check_windows_runtime_manifest(tmp_path)

    (tmp_path / "vcruntime140.dll").write_bytes(b"old runtime")

    with pytest.raises(RuntimeError, match="选定的文件不一致"):
        smoke.check_windows_runtime_manifest(tmp_path)


def test_runtime_manifest_is_required(tmp_path: Path) -> None:
    """缺少来源清单时不能声称运行库已按选定来源随包。"""
    with pytest.raises(RuntimeError, match="未包含 Windows 运行库清单"):
        smoke.check_windows_runtime_manifest(tmp_path)


def test_windows_packaging_requires_transitive_crt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """即使 libclang 的直接 CRT 已存在，也必须携带其间接依赖。"""
    library = tmp_path / "clang" / "native" / "libclang.dll"
    library.parent.mkdir(parents=True)
    library.touch()
    (tmp_path / "MSVCP140.dll").touch()
    imports = {
        "libclang.dll": {"kernel32.dll", "msvcp140.dll"},
        "msvcp140.dll": {"vcruntime140.dll"},
        "vcruntime140.dll": {"api-ms-win-crt-runtime-l1-1-0.dll"},
    }
    def read_imports(path: Path) -> set[str]:
        """只读模拟导入关系，宿主机是否已安装 CRT 不影响测试。"""
        return imports[path.name.lower()]

    monkeypatch.setattr(smoke, "pe_import_names", read_imports)

    with pytest.raises(RuntimeError, match="缺少运行库 vcruntime140.dll"):
        smoke.check_windows_runtime(tmp_path, library)

    (tmp_path / "vcruntime140.dll").touch()
    evidence = smoke.check_windows_runtime(tmp_path, library)
    assert evidence["MSVCP140.dll"] == ["vcruntime140.dll"]


def test_onefile_requires_retained_native_payload(tmp_path: Path) -> None:
    """单文件可启动不能替代其生成负载中原生库的检查。"""
    artifact = tmp_path / "repopath.exe"
    artifact.touch()

    with pytest.raises(RuntimeError, match="未包含原生库"):
        smoke.relocate_artifact("onefile", artifact, tmp_path, tmp_path)


def test_onefile_bootstrap_must_start_without_external_crt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """运行库随负载压缩时，启动入口不能在解包前就要求加载它。"""
    imports = {"kernel32.dll", "api-ms-win-crt-runtime-l1-1-0.dll"}

    def read_imports(path: Path) -> set[str]:
        return imports

    monkeypatch.setattr(smoke, "pe_import_names", read_imports)
    artifact = tmp_path / "repopath.exe"
    smoke.check_windows_onefile_bootstrap(artifact)

    imports.add("vcruntime140.dll")
    with pytest.raises(RuntimeError, match="启动入口仍依赖外部运行库"):
        smoke.check_windows_onefile_bootstrap(artifact)


@pytest.mark.parametrize("dynamic, resolved, error", [
    ("(RUNPATH) [/home/builder/site-packages/clang/native]", "", "RPATH"),
    ("(RPATH) [$ORIGIN/../..]", "libstdc++.so.6 => not found", "未满足"),
])
def test_linux_packaging_rejects_developer_machine_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    dynamic: str, resolved: str, error: str,
) -> None:
    """绝对构建路径和缺失共享库都必须让验收失败。"""
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """模拟 Linux ELF 工具，测试不依赖宿主系统。"""
        output = resolved if command[0] == "ldd" else dynamic
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", run)

    with pytest.raises(RuntimeError, match=error):
        smoke.check_linux_runtime(tmp_path / "libclang.so")
